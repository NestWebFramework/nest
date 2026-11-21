"""Versions: Nest's is nest-core's (one place, read everywhere); every package and every
application keeps its own in its module.yml, and its README (and its documentation page)
says the same, so raising one without the other is caught here."""

import re
from pathlib import Path

import pytest
import yaml

import nest

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT.parent  # the sites' repositories beside Nest's, when checked out


def version_in(pyproject: Path) -> str:
    return re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M).group(1)


def test_nest_has_one_version():
    core = version_in(ROOT / "packages/nest-core/pyproject.toml")
    assert nest.__version__ == core
    assert version_in(ROOT / "pyproject.toml") == core  # the workspace says the same
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"**Version {core}**" in readme
    assert f"## {core}" in (ROOT / "docs/changelog.md").read_text(encoding="utf-8")
    assert f"**Version {core}**" in (ROOT / "packages/nest-core/README.md").read_text(
        encoding="utf-8"
    )


MANIFESTS = sorted(p for p in ROOT.glob("**/src/*/module.yml") if ".venv" not in p.parts)


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: str(p.parents[2].relative_to(ROOT)))
def test_every_package_states_its_version(manifest):
    v = yaml.safe_load(manifest.read_text(encoding="utf-8"))["module"]["version"]
    pkg = manifest.parents[2]
    assert version_in(pkg / "pyproject.toml") == v, "pyproject.toml and module.yml disagree"
    readme = pkg / "README.md"
    assert readme.is_file(), "no README (uv run python tools/package_readmes.py)"
    assert f"**Version {v}**" in readme.read_text(encoding="utf-8"), (
        "the README states another version"
    )


@pytest.mark.parametrize(
    "app", sorted(p.parent for p in ROOT.glob("applications/*/module.yml")), ids=lambda p: p.name
)
def test_every_application_of_nest_states_its_version(app):
    v = yaml.safe_load((app / "module.yml").read_text(encoding="utf-8"))["module"]["version"]
    assert f"**Version {v}**" in (app / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("site", ["gari", "morlaca", "transilpedia", "regionalisme"])
def test_the_sites_readmes_say_their_version(site):
    manifest = SITES / site / "module.yml"
    if not manifest.is_file():
        pytest.skip(f"{site} is not checked out beside Nest")
    v = yaml.safe_load(manifest.read_text(encoding="utf-8"))["module"]["version"]
    assert f"**Version {v}**" in (SITES / site / "README.md").read_text(encoding="utf-8")
