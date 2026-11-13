"""Gallery pages, and the shortcodes that put a gallery into any page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from nest_db import Database
from nest_media import media_url

from nest import bound, render, translator
from nest.host import module_state
from nest_gallery import service

router = APIRouter()
index_router = APIRouter()  # mounted unless the application keeps its own page at the route


def _base(request: Request) -> str:
    return module_state(request, "gallery")["base"]


@index_router.get("/")
def index(request: Request, db: Database = bound(Database)):
    return render(request, "gallery/index.html", cards=service.cards(db, None), base=_base(request))


@router.get("/{slug}/")
def collection(request: Request, slug: str, db: Database = bound(Database)):
    c = service.by_slug(db, slug)
    if c is None:
        raise HTTPException(404)
    children = service.cards(db, c.id)
    return render(
        request,
        "gallery/collection.html",
        collection=c,
        cards=children,
        photos=[] if children else service.photos(db, c.id),
        base=_base(request),
    )


def embed(host: Any, request: Any, c: Any) -> str:
    """A collection inside another page: an album's tiles, or a gallery's photos."""
    db = host.bound("nest.db")
    children = service.cards(db, c.id)
    t = translator(request)
    return host.render_block(
        "gallery/embed.html",
        "embed",
        collection=c,
        cards=children,
        photos=[] if children else service.photos(db, c.id),
        base=host.state["base"],
        media=lambda key: media_url(request, key),
        _=t.gettext,
        ngettext=t.ngettext,
    )


def shortcodes(host: Any) -> None:
    """[gallery slug=...], [album slug=...], and the tags the WordPress plugins left behind."""
    db = host.bound("nest.db")

    def by_attrs(attrs: dict[str, str]) -> Any:
        if attrs.get("slug"):
            return service.by_slug(db, attrs["slug"])
        return None

    def answer(found: Any, ctx: Any) -> str:
        request = getattr(ctx, "request", ctx)
        return embed(host, request, found) if found is not None and request is not None else ""

    host.shortcode("gallery", lambda attrs, ctx: answer(by_attrs(attrs), ctx))
    host.shortcode("album", lambda attrs, ctx: answer(by_attrs(attrs), ctx))

    def legacy(source: str, key: str = "id"):
        def handler(attrs: dict[str, str], ctx: Any) -> str:
            value = attrs.get(key, "").split(",")[0].strip()
            return answer(
                service.by_alias(db, source, int(value)) if value.isdigit() else None, ctx
            )

        return handler

    host.shortcode("Best_Wordpress_Gallery", legacy("bwg_shortcode"))  # Photo Gallery (10Web)
    host.shortcode("nggallery", legacy("ngg_gallery"))  # NextGEN, old form
    host.shortcode("ngg", legacy("ngg_gallery", "ids"))  # NextGEN, [ngg src="galleries" ids="1"]
