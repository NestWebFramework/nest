"""Templates: one Jinja environment per application, pages and fragments alike.

Lookup order lets an application override anything without forking it:

1. ``<app>/templates/``          the application's own overrides
2. the theme's ``templates/``     layouts, widgets (``layout.html``)
3. ``<module>/...``               each module's templates, under its name

So ``glossary/index.html`` is the glossary module's page unless the theme or
the application ships its own. A handler answers both clients from one
template: the whole page, or one ``{% block %}`` of it for htmx.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import (
    BaseLoader,
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    PrefixLoader,
    StrictUndefined,
    select_autoescape,
)


def make_environment(
    app_root: Path, theme_dir: Path | None, module_dirs: Mapping[str, Path]
) -> Environment:
    loaders: list[BaseLoader] = []
    if (app_root / "templates").is_dir():
        loaders.append(FileSystemLoader(app_root / "templates"))
    if theme_dir is not None:
        loaders.append(FileSystemLoader(theme_dir))
    loaders.append(
        PrefixLoader({name: FileSystemLoader(path) for name, path in module_dirs.items()})
    )
    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def is_htmx(request: Request) -> bool:
    """An htmx request that wants a fragment (a boosted one wants the page)."""
    return (
        request.headers.get("hx-request") == "true" and request.headers.get("hx-boosted") != "true"
    )


def render_block(env: Environment, name: str, block: str, context: Mapping[str, Any]) -> str:
    template = env.get_template(name)
    if block not in template.blocks:
        raise LookupError(f"{name} has no block '{block}'")
    return "".join(template.blocks[block](template.new_context(dict(context))))


def render(
    request: Request,
    name: str,
    context: Mapping[str, Any] | None = None,
    *,
    fragment: str | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    **values: Any,
) -> HTMLResponse:
    """The page, or only ``fragment`` when htmx asked: one handler for both clients."""
    nest = request.app.state.nest
    ctx = {**nest.template_context(request), **(context or {}), **values}
    if fragment and is_htmx(request):
        body = render_block(nest.templates, name, fragment, ctx)
    else:
        body = nest.templates.get_template(name).render(ctx)
    return HTMLResponse(body, status_code=status_code, headers=dict(headers or {}))
