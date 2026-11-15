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


# A page asked with this header answers only one of its blocks (``content`` by default), so
# an application can show any module's page inside its own screen: a game's drawer.
EMBED_HEADER = "X-Nest-Embed"


def is_htmx(request: Request) -> bool:
    """An htmx request that wants a fragment (a boosted one wants the page)."""
    return (
        request.headers.get("hx-request") == "true" and request.headers.get("hx-boosted") != "true"
    )


def render_block(env: Environment, name: str, block: str, context: Mapping[str, Any]) -> str:
    template = env.get_template(name)
    if block not in template.blocks:
        raise LookupError(f"{name} has no block '{block}'")
    ctx = template.new_context(dict(context))
    # A block may use what the template sets up outside any block: its
    # {% import %}s and {% set %}s. Run the template's top level until it first
    # produces output (for a child template, that is where the layout begins),
    # which leaves those names in the context, then render only the block.
    top = template.root_render_func(ctx)
    try:
        next(top)
    except StopIteration:
        pass
    finally:
        top.close()
    return "".join(template.blocks[block](ctx))


def render(
    request: Request,
    template: str,
    context: Mapping[str, Any] | None = None,
    /,
    *,
    fragment: str | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    **values: Any,
) -> HTMLResponse:
    """The page, or only ``fragment`` when htmx asked: one handler for both clients.

    Template values are keyword arguments; only ``fragment``, ``status_code``
    and ``headers`` are taken by ``render`` itself (the first three parameters
    are positional-only, so ``name=`` or ``request=`` reach the template).
    """
    from nest.i18n import translator  # noqa: PLC0415 - the host imports this module first

    nest = request.app.state.nest
    ctx = {**nest.template_context(request), **(context or {}), **values}
    if "/" in template:  # a module's template: the application may reword that module alone
        ctx["_"], ctx["ngettext"] = translator(request).scoped(template.split("/", 1)[0])
    out_headers = dict(headers or {})
    embed = request.headers.get(EMBED_HEADER)
    if embed is not None:
        # an application shows this page inside its own screen (a game's drawer): only its
        # content, the block it names (content by default), never the frame
        block = embed.strip() or "content"
        if block not in nest.templates.get_template(template).blocks:
            return HTMLResponse(f"no block '{block}' to embed", status_code=400)
        body = render_block(nest.templates, template, block, ctx)
    elif fragment and is_htmx(request):
        body = render_block(nest.templates, template, fragment, ctx)
    else:
        body = nest.templates.get_template(template).render(ctx)
    out_headers["vary"] = ", ".join(
        filter(None, [out_headers.get("vary"), "HX-Request", EMBED_HEADER])
    )
    return HTMLResponse(body, status_code=status_code, headers=out_headers)
