"""Scaffolding: a new module or application that validates and runs as written."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


def _check(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ValueError("a name is lower-case letters, digits and '-'")
    return name


def _write(files: dict[Path, str]) -> None:
    for path, body in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def new_module(name: str, into: Path) -> Path:
    """A packaged module: modules/<name>/ with pyproject, manifest, code, template, test."""
    _check(name)
    package = "nest_" + name.replace("-", "_")
    root = into / name
    if root.exists():
        raise FileExistsError(root)
    src = root / "src" / package
    _write(
        {
            root / "pyproject.toml": f"""[project]
name = "nest-{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["nest-core"]

[project.entry-points."nest.modules"]
{name} = "{package}"

[build-system]
requires = ["uv_build>=0.9,<0.14"]
build-backend = "uv_build"
""",
            src / "module.yml": f"""module:
  name: {name}
  id: nest.module.{name}
  type: module
  title: {name.replace("-", " ").title()}
  version: 0.1.0
  description: >
    What this module is for.
  license: MIT
  created: "{date.today().isoformat()}"

# the nest-core versions it works with (a registry refuses a package without)
nest: ">=0.2,<1"

main: {package}

provides:
  import: {package}
  exports: []

docs:
  title: {name.replace("-", " ").title()}
  section: modules
""",
            src / "__init__.py": f'''"""The {name} module."""

from fastapi import APIRouter, Request

from nest import ModuleHost, render

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return render(request, "{name}/index.html")


def setup(host: ModuleHost) -> None:
    host.mount(router)
''',
            src / "templates" / "index.html": """{% extends "layout.html" %}
{% block content %}
<h1>"""
            + name
            + """</h1>
{% endblock %}
""",
        }
    )
    return root


def new_app(name: str, into: Path) -> Path:
    """An application with one local module mounted at /."""
    _check(name)
    root = into / name
    if root.exists():
        raise FileExistsError(root)
    home = root / "modules" / "home"
    _write(
        {
            root / "module.yml": f"""module:
  name: {name}
  id: nest.app.{name}
  type: application
  title: {name.replace("-", " ").title()}
  version: 0.1.0
  created: "{date.today().isoformat()}"

application:
  title: {name.replace("-", " ").title()}
  port: 8000
  theme: base

modules:
  - name: home
    route: /

deploy:
  service: {name}
""",
            home / "module.yml": f"""module:
  name: home
  id: nest.app.{name}.home
  type: module
  version: 0.1.0

main: home
""",
            home / "home" / "__init__.py": """from fastapi import APIRouter, Request

from nest import ModuleHost, render

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return render(request, "home/index.html")


def setup(host: ModuleHost) -> None:
    host.mount(router)
""",
            home / "templates" / "index.html": """{% extends "layout.html" %}
{% block content %}
<h1>{{ app.title }}</h1>
<p>It runs.</p>
{% endblock %}
""",
        }
    )
    return root
