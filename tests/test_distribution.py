"""What a package needs to be distributed (built as a wheel, installed from a registry):
its manifest travels inside it, everything the manifest names is inside it too, and it says
which nest-core versions it works with."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from nest.manifest import load_manifest

REPO = Path(__file__).resolve().parents[1]
FOLDERS = ("modules", "interfaces", "providers", "themes", "engines")


def packages():
    for folder in FOLDERS:
        for project in sorted((REPO / folder).rglob("pyproject.toml")):
            if ".venv" in project.parts:
                continue
            yield project.parent


@pytest.mark.parametrize("project", list(packages()), ids=lambda p: p.name)
def test_the_manifest_travels_in_the_package(project):
    assert not (project / "module.yml").exists(), "module.yml belongs in src/<package>/"
    found = list((project / "src").glob("*/module.yml"))
    assert len(found) == 1, found
    m = load_manifest(found[0].parent)
    root = Path(m.root)
    assert root == found[0].parent
    assert m.nest, "it says which nest-core versions it works with (nest:)"
    import tomllib  # noqa: PLC0415

    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    assert version == m.module.version, (
        f"pyproject.toml says {version}, module.yml {m.module.version}"
    )
    named = [m.templates, m.static, *(item.file for item in m.locales)]
    named += [f"{m.static or 'static'}/{s}" for s in (*m.styles, *m.admin_styles)]
    db = m.raw.get("db") or {}
    if isinstance(db, dict) and db.get("migrations"):
        named.append(db["migrations"])
    for item in m.raw.get("vendored") or []:
        named.append(item["file"])
    for relative in filter(None, named):
        assert (root / relative).exists(), f"{relative} is not in the package"


@pytest.mark.skipif(not shutil.which("uv"), reason="uv builds the wheel")
def test_a_built_wheel_carries_its_manifest(tmp_path):
    subprocess.run(
        ["uv", "build", str(REPO / "modules" / "forum"), "--wheel", "-o", str(tmp_path), "-q"],
        check=True,
        env={k: v for k, v in __import__("os").environ.items() if k != "VIRTUAL_ENV"},
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "nest_forum/module.yml" in names
    assert "nest_forum/migrations/versions/0001_forum.py" in names or any(
        n.startswith("nest_forum/migrations/versions/") for n in names
    )
    assert any(n.startswith("nest_forum/templates/") for n in names)
