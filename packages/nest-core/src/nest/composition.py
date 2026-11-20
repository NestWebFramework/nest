"""An application's composition: which of its modules run, as its administrator chose.

The manifest (module.yml) says what the application is made of by default: its core
modules, which always run, and the others, each enabled or not. What the administrator
then chooses (in the admin panel, or with ``nest modules``) is kept in the workspace, in
``data/modules.yml``, and laid over the manifest when the application is made:

    theme: paper                               # the look, over application.theme
    modules:
      gallery: {enabled: false}
      forum: {enabled: true, route: /forum}    # a module the manifest does not list

So module.yml stays the code's (a deploy brings it), the choices stay the site's (a
backup keeps them), and a core module can never be turned off from either place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nest.manifest import Instance, Manifest

FILE = Path("data") / "modules.yml"


class CompositionError(ValueError):
    pass


@dataclass
class Choice:
    enabled: bool
    route: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"enabled": self.enabled}
        if self.route:
            out["route"] = self.route
        if self.config:
            out["config"] = self.config
        return out


def path(workspace: Path) -> Path:
    return workspace / FILE


def _raw(workspace: Path) -> dict[str, Any]:
    file = path(workspace)
    if not file.is_file():
        return {}
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise CompositionError(f"{file}: expected a mapping")
    return raw


def load_theme(workspace: Path) -> str | None:
    """The theme the administrator chose (None: the manifest's)."""
    theme = _raw(workspace).get("theme")
    return str(theme) if theme else None


def load(workspace: Path) -> dict[str, Choice]:
    """The administrator's choices, by module ({} when none were made)."""
    file = path(workspace)
    if not file.is_file():
        return {}
    raw = _raw(workspace)
    modules = raw.get("modules", {})
    if not isinstance(modules, dict):
        raise CompositionError(f"{file}: expected a 'modules:' mapping")
    out = {}
    for name, value in modules.items():
        if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
            raise CompositionError(f"{file}: {name} needs 'enabled: true' or 'enabled: false'")
        out[str(name)] = Choice(
            enabled=value["enabled"],
            route=value.get("route"),
            config=dict(value.get("config") or {}),
        )
    return out


_KEEP = object()


def save(workspace: Path, choices: dict[str, Choice] | None = None, theme: Any = _KEEP) -> None:
    """Write the choices (``choices`` None: the modules as they are; ``theme`` left out:
    the theme as it is, None: back to the manifest's)."""
    file = path(workspace)
    file.parent.mkdir(parents=True, exist_ok=True)
    if choices is None:
        choices = load(workspace)
    if theme is _KEEP:
        theme = load_theme(workspace)
    body: dict[str, Any] = {"modules": {name: c.as_dict() for name, c in sorted(choices.items())}}
    if theme:
        body = {"theme": theme, **body}
    tmp = file.with_suffix(".tmp")
    tmp.write_text(
        "# The modules and the theme this application runs, as its administrator chose\n"
        "# (nest modules, nest themes, the admin panel), over its module.yml.\n"
        + yaml.safe_dump(body, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    os.replace(tmp, file)


def compose(manifest: Manifest, choices: dict[str, Choice]) -> list[Instance]:
    """The manifest's modules with the choices laid over them."""
    out = []
    listed = {inst.name for inst in manifest.modules}
    for inst in manifest.modules:
        choice = choices.get(inst.name)
        if choice is None:
            out.append(inst)
            continue
        if inst.core and not choice.enabled:
            raise CompositionError(f"{inst.name} is a core module of {manifest.name}")
        update: dict[str, Any] = {"enabled": choice.enabled}
        if choice.route:
            update["route"] = choice.route
        if choice.config:
            update["config"] = {**inst.config, **choice.config}
        out.append(inst.model_copy(update=update))
    for name, choice in sorted(choices.items()):
        if name not in listed and choice.enabled:
            out.append(
                Instance(name=name, route=choice.route, config=dict(choice.config), added=True)
            )
    return out
