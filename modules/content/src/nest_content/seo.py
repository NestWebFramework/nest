"""What search engines and feed readers ask a site for: /sitemap.xml, /robots.txt, /feed/.

Every address in them is absolute, made from the ``site_url`` setting (the
address the public uses, https://morlaca.ro) or, when that is empty, from the
request. A site that is not in production asks robots to stay away entirely, so
a test copy never competes with the real one. robots.txt is a template
(content/robots.txt), so an application can write its own.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from markupsafe import Markup
from nest_db import Database

from nest import bound
from nest.host import module_state
from nest_content import service

router = APIRouter()  # the feed: always the content module's
files = APIRouter()  # sitemap and robots: its own only where the seo module is not
_SHORTCODE = re.compile(
    r"\[/?[A-Za-z][\w-]*(?:\s[^\]]*)?\]"
)  # a shortcode says nothing to a reader
FEED_SIZE = 20


def site_url(request: Request) -> str:
    """The site's public address, without a trailing slash (the seo module's, when the
    application includes it and sets one)."""
    configured = request.app.state.nest.lookup("seo.site_url", None) or ""
    configured = configured or str(
        module_state(request, "content")["settings"].get("site_url") or ""
    )
    return (configured or str(request.base_url)).rstrip("/")


def absolute(request: Request, path: str) -> str:
    if not path or path.startswith(("http://", "https://")):
        return path
    return site_url(request) + (path if path.startswith("/") else "/" + path)


def _xml(body: str, media_type: str) -> Response:
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + body,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@files.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Database = bound(Database)) -> Response:
    from nest_content import translated  # noqa: PLC0415

    state = module_state(request, "content")
    registry = state["types"]
    rows = [("/", None)] + service.sitemap(db)
    for locale in translated.others(registry):  # each translated page at its own address
        entries, terms = translated.published_texts(db, registry, locale)
        rows += [(state["language_url"](row.path, locale), row.updated_at) for _e, row in entries]
        rows += [(state["language_url"](row.path, locale), None) for _t, row in terms]
    urls = "".join(
        f"<url><loc>{escape(absolute(request, path))}</loc>"
        + (f"<lastmod>{when.date().isoformat()}</lastmod>" if when else "")
        + "</url>"
        for path, when in rows
    )
    return _xml(
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        "application/xml",
    )


def _rfc822(when: datetime | None) -> str:
    return format_datetime((when or datetime.now(UTC)).replace(tzinfo=UTC))


@router.get("/feed/", include_in_schema=False)
def feed(request: Request, db: Database = bound(Database)) -> Response:
    return feed_of(request, db)


def feed_of(request: Request, db: Any, term: Any = None) -> Response:
    """The newest entries as RSS: the site's (/feed/), or one category's or tag's
    (/category/stiai-ca/feed/, the address WordPress gave it)."""
    state = module_state(request, "content")
    nest = request.app.state.nest
    from nest_content import translated  # noqa: PLC0415

    types = [t for t, s in state["types"].types.items() if not s.hierarchical]
    entries, _ = service.listing(
        db, types=types, term_id=term.id if term is not None else None, per_page=FEED_SIZE
    )
    # /en/feed/: the entries in English (the original's where there is none yet), linked
    # at their English addresses
    locale = str(getattr(request.state, "locale", "") or "")
    prefix = str(getattr(request.state, "url_prefix", "") or "")
    entries = [
        e
        for e in translated.show_entries(db, state["types"], entries, locale)
        if not getattr(e, "fallback", False)
    ]
    items = "".join(
        "<item>"
        f"<title>{escape(e.title)}</title>"
        f"<link>{escape(absolute(request, prefix + e.path))}</link>"
        f'<guid isPermaLink="true">{escape(absolute(request, prefix + e.path))}</guid>'
        f"<pubDate>{_rfc822(e.published_at)}</pubDate>"
        f"<description>{escape(summary(e))}</description>"
        "</item>"
        for e in entries
    )
    language = locale or nest.catalogs.default
    return _xml(
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{escape(nest.title + (' · ' + term.name if term is not None else ''))}</title>"
        f"<link>{escape(absolute(request, prefix + (term.path if term is not None else '/')))}</link>"
        f'<atom:link href="{escape(absolute(request, prefix + ((term.path or "/") if term is not None else "/") + "feed/"))}" rel="self" type="application/rss+xml"/>'
        f"<description>{escape(nest.manifest.module.description or nest.title)}</description>"
        + (f"<language>{escape(language)}</language>" if language else "")
        + f"{items}</channel></rss>",
        "application/rss+xml",
    )


@router.get("/feed", include_in_schema=False)
def feed_without_slash() -> RedirectResponse:
    return RedirectResponse("/feed/", status_code=301)


@files.get("/robots.txt", include_in_schema=False)
def robots(request: Request) -> Response:
    nest = request.app.state.nest
    closed = [nest.admin_root] if nest.admin_root else []
    for unit in nest.plan.units:  # where people sign in has nothing to index
        if unit.name == "auth" and unit.instance and unit.instance.route:
            closed.append(unit.instance.route)
    text = nest.templates.get_template("content/robots.txt").render(
        production=nest.production,
        closed=[c.rstrip("/") + "/" for c in closed] + ["/_nest/", "/search"],
        sitemap=absolute(request, "/sitemap.xml"),
    )
    return Response(
        text, media_type="text/plain", headers={"Cache-Control": "public, max-age=3600"}
    )


# --- for pages ---------------------------------------------------------------------


def summary(entry: Any, length: int = 160) -> str:
    """A sentence or two about an entry: its excerpt, or its text's beginning."""
    source = entry.excerpt or entry.body or ""
    if not entry.excerpt and len(source) > length * 15:  # the opening is enough: no need
        source = re.sub(r"<[^>]*$", "", source[: length * 15])  # to read a long article whole
    text = Markup(source).striptags()
    text = " ".join(_SHORTCODE.sub(" ", text).split())
    if len(text) <= length:
        return text
    cut = text[: length - 1].rsplit(" ", 1)[0]
    return cut + "…"
