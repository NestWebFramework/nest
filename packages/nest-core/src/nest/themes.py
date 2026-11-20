"""An application's look: the themes installed, the one it uses, switching to another.

The manifest names a theme (``application.theme``); the administrator may choose another
installed theme, kept in the workspace beside the modules (nest.composition), so a deploy
never undoes it. A switch is tried before it is kept: the application is made with the
new theme and its pages are rendered (the home page, a page that is not there, and
the admin panel's frame). A theme that cannot show them is refused, so a broken theme
can never take the site, or the admin panel needed to switch back, down with it. Then
the running site is reloaded, as for a module change.

A theme keeps the theme contract (``check``): it provides, itself or through the theme it
extends, ``layout.html`` with the blocks every page fills (title, head, header, nav,
language, content, footer), ``error.html`` and ``widgets/language.html``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest import composition
from nest.catalog import Catalog, Entry
from nest.manifest import load_manifest
from nest.workspace import resolve_workspace

REQUIRED = ("layout.html", "error.html", "widgets/language.html")
BLOCKS = ("title", "head", "header", "nav", "language", "content", "footer")


class ThemeError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class ThemeInfo:
    name: str
    title: str
    description: str
    version: str
    active: bool
    default: bool  # the manifest's
    extends: str | None
    colors: dict[str, str] = field(default_factory=dict)  # its manifest's preview: colours


def _context(app_dir: Path, environ: Mapping[str, str]) -> tuple[Any, Path, Catalog]:
    manifest = load_manifest(app_dir)
    return manifest, resolve_workspace(manifest.name, dict(environ)), Catalog.discover(app_dir)


def active(app_dir: str | Path, environ: Mapping[str, str] | None = None) -> str | None:
    app_dir = Path(app_dir).resolve()
    manifest, workspace, _ = _context(app_dir, dict(os.environ if environ is None else environ))
    default = manifest.application.theme if manifest.application else None
    return composition.load_theme(workspace) or default


def themes(app_dir: str | Path, environ: Mapping[str, str] | None = None) -> list[ThemeInfo]:
    """Every installed theme, the one in use first."""
    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    manifest, workspace, catalog = _context(app_dir, environ)
    default = manifest.application.theme if manifest.application else None
    using = composition.load_theme(workspace) or default
    out = []
    for entry in catalog.of_type("theme"):
        m = entry.manifest
        colors = m.raw.get("preview") if isinstance(m.raw.get("preview"), dict) else {}
        out.append(
            ThemeInfo(
                name=entry.name,
                title=m.module.title or entry.name,
                description=" ".join((m.module.description or "").split()),
                version=m.module.version,
                active=entry.name == using,
                default=entry.name == default,
                extends=m.extends,
                colors={str(k): str(v) for k, v in colors.items()},
            )
        )
    return sorted(out, key=lambda t: (not t.active, t.name))


def try_theme(app_dir: Path, environ: Mapping[str, str], name: str) -> list[str]:
    """Make the application with the theme and render its pages; the problems found."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from nest.host import close_providers, create_app  # noqa: PLC0415

    env = {**environ, "NEST_ROLE": "web"}  # migrations as the site runs them
    env.pop("NEST_ENGINE_URL", None)  # a game's pages wait for its engine; its frame does not
    try:
        app = create_app(app_dir, environ=env, theme=name)
    except Exception as e:  # noqa: BLE001 - told to the administrator
        return [f"the application cannot be made with {name}: {e}"]
    nest = app.state.nest
    problems = []
    try:
        client = TestClient(app, raise_server_exceptions=False)
        paths = ["/", "/_nest/no-such-page"]
        if nest.admin_root is not None:
            paths.append((nest.admin_root or "") + "/")
        for path in paths:
            r = client.get(path, headers={"accept": "text/html"}, follow_redirects=True)
            if r.status_code >= 500:
                problems.append(f"{name} cannot show {path} ({r.status_code})")
    finally:
        close_providers(nest)
    return problems


def use(
    app_dir: str | Path,
    name: str | None,
    environ: Mapping[str, str] | None = None,
    *,
    who: str = "",
    reload: bool = True,
) -> list[str]:
    """Make ``name`` the application's theme (None: back to its manifest's); returns notes."""
    from nest.modules import _record, reload_running  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    manifest, workspace, catalog = _context(app_dir, environ)
    default = manifest.application.theme if manifest.application else None
    target = name or default
    entry, _ = catalog.find(target) if target else (None, None)
    if entry is None or entry.type != "theme":
        problems = [f"'{target}' is not an installed theme"]
        _record(workspace, who, {"theme": [str(target)]}, "refused", problems)
        raise ThemeError(problems)
    problems = check_theme(entry, list(catalog)) + try_theme(app_dir, environ, entry.name)
    if problems:
        _record(workspace, who, {"theme": [entry.name]}, "refused", problems)
        raise ThemeError(problems)
    composition.save(workspace, theme=None if entry.name == default else entry.name)
    _record(workspace, who, {"theme": [entry.name]}, "done", [])
    notes = []
    if reload and not reload_running(workspace):
        notes.append("restart the application to apply it (it is not run by nest serve)")
    return notes


# --- the theme contract ---------------------------------------------------------------------


_BLOCK = re.compile(r"{%-?\s*block\s+([a-z_]+)")


def _chain(entry: Entry, known: list[Entry]) -> list[Entry]:
    by_name = {e.name: e for e in known}
    chain, current = [], entry
    while current is not None and current not in chain:
        chain.append(current)
        parent = current.manifest.extends
        current = by_name.get(parent) if parent else None
    return chain


def check_theme(entry: Entry, known: list[Entry]) -> list[str]:
    """What the theme (with the ones it extends) lacks of the theme contract."""
    chain = _chain(entry, known)
    folders = [d for t in chain if (d := t.manifest.folder(t.manifest.templates, "templates"))]
    problems = []
    if entry.manifest.extends and len(chain) < 2:
        problems.append(f"{entry.name} extends '{entry.manifest.extends}', which is not installed")
    if entry.manifest.extends and entry.manifest.extends not in entry.manifest.deps:
        problems.append(f"{entry.name} extends {entry.manifest.extends} but does not depend on it")
    for template in REQUIRED:
        if not any((f / template).is_file() for f in folders):
            problems.append(f"{entry.name} has no {template} (the theme contract)")
    layout = next((f / "layout.html" for f in folders if (f / "layout.html").is_file()), None)
    if layout is not None:
        found = set(_BLOCK.findall(layout.read_text(encoding="utf-8")))
        missing = [b for b in BLOCKS if b not in found]
        if missing:
            problems.append(f"{entry.name}'s layout.html lacks the blocks: {', '.join(missing)}")
    return problems


def check(entries: list[Entry], known: list[Entry]) -> list[Any]:
    """For ``nest validate --strict``: every theme keeps the contract."""
    from nest.boundaries import Finding  # noqa: PLC0415

    out = []
    for entry in entries:
        if entry.type == "theme":
            for problem in check_theme(entry, known):
                out.append(Finding("error", entry.name, str(entry.manifest.source), problem))
    return out
