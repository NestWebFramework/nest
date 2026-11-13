from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def module_yml(name: str, type_: str = "module", version: str = "0.1.0", extra: str = "") -> str:
    main = (
        ""
        if type_ in ("application", "interface", "theme")
        else f"main: {name.replace('-', '_')}\n"
    )
    kind = {"module": "module", "provider": "provider", "application": "app"}.get(type_, type_)
    return (
        f"module:\n  name: {name}\n  id: test.{kind}.{name}\n  type: {type_}\n  version: {version}\n"
        + main
        + textwrap.dedent(extra)
    )


@pytest.fixture
def app_dir(tmp_path: Path):
    """Build an application folder: ``app_dir({"module.yml": ..., "modules/x/module.yml": ...})``."""

    def build(files: dict[str, str]) -> Path:
        return write(tmp_path / "app", files)

    return build
