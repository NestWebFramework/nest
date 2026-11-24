"""The content module over HTTP.

Public pages are not routes: an entry or a term is found by its stored path
when no route matched (a fallback), so a site keeps whatever addresses it had
(/istorie/biserica-din-morlaca/) without a catch-all that would shadow other
modules. Media is served from nest.storage. Editors work in the admin panel
(<admin route>/content), given to it as the module's admin pages.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from markupsafe import Markup
from nest_auth import CurrentUser, require_role
from nest_db import Database
from nest_media import media_base, responsive_images
from nest_search import Search
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, is_htmx, render, toast, translator
from nest.host import module_state
from nest_content import seo, service, translated
from nest_content.html import embed_videos, link_list, sanitize, video, youtube_id
from nest_content.models import STATUSES, Entry
from nest_content.service import ContentError, EntryData

router = APIRouter()
admin = APIRouter()  # the editor: the admin panel mounts it at <admin route>/content
editor = require_role("editor")


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "content")


def locale_of(request: Any) -> str:
    """The language a page is in ("" when there is no request: the default's)."""
    state = getattr(request, "state", None)
    return str(getattr(state, "locale", "") or "") if state is not None else ""


def _bindings(request: Request) -> tuple[Any, Any, Any]:
    b = request.app.state.nest.bindings
    return b.get("nest.db"), b.get("nest.search"), b.get("nest.storage")


# --- shortcodes --------------------------------------------------------------------


@dataclass
class Context:
    """What a shortcode handler is given when a content page expands it."""

    db: Any
    entry: Entry | None
    request: Any = None


def catlist(attrs: dict[str, str], ctx: Context) -> str:
    """[catlist id=3 numberposts=10 orderby=title order=asc] (WordPress's List Category Posts)."""
    term = None
    if attrs.get("categorypage", "").lower() == "yes" and ctx.entry is not None:
        # The posts of this post's own (first) category.
        own = service.terms_of(ctx.db, ctx.entry.id).get("category", [])
        term = own[0] if own else None
    elif attrs.get("id", "").isdigit():
        term = service.term_by(ctx.db, "category", legacy_id=int(attrs["id"]))
    elif attrs.get("name"):
        term = service.term_by(ctx.db, "category", slug=attrs["name"], name=attrs["name"])
    if term is None:
        return ""
    limit = int(attrs.get("numberposts", "-1") or -1)
    order = "title" if attrs.get("orderby", "date") == "title" else "date"
    entries, _ = service.listing(
        ctx.db, term_id=term.id, per_page=500 if limit < 0 else min(limit, 500), order=order
    )
    if attrs.get("order", "").lower() == "asc" and order == "date":
        entries.reverse()
    if attrs.get("order", "").lower() == "desc" and order == "title":
        entries.reverse()
    own = ctx.entry.id if ctx.entry else None
    if ctx.request is not None:
        registry = _state(ctx.request)["types"]
        entries = translated.show_entries(ctx.db, registry, entries, locale_of(ctx.request))
    return link_list([(e.title, e.path) for e in entries if e.id != own])


def wp_gallery(attrs: dict[str, str], ctx: Context) -> str:
    """[gallery ids="12,13"]: the images, by their WordPress attachment ids."""
    from markupsafe import escape

    images = []
    for raw in attrs.get("ids", "").split(","):
        if raw.strip().isdigit():
            m = service.media_by_legacy(ctx.db, int(raw))
            if m is not None:
                images.append(m)
    if not images:
        return ""
    from nest_media import media_url

    figures = "".join(
        f'<figure><a href="{media_url(ctx.request, m.key)}"><img src="{media_url(ctx.request, m.key)}" alt="{escape(m.alt)}" loading="lazy"></a></figure>'
        for m in images
    )
    return f'<div class="gallery">{figures}</div>'


def youtube(attrs: dict[str, str], ctx: Context) -> str:
    """[youtube url="https://www.youtube.com/watch?v=..."] or [youtube id="..."]."""
    vid = youtube_id(attrs.get("id") or attrs.get("url") or "")
    if vid is None:
        return ""
    label = translator(ctx.request)("Play the video") if ctx.request else "Play the video"
    return video(vid, attrs.get("title") or label)


# --- search ------------------------------------------------------------------------


@router.get("/search")
def search(request: Request, q: str = "", page: int = 1, index: Search = bound(Search)):
    q = q.strip()[:200]
    size = 20
    page = max(1, min(page, 500))
    kind = translated.kind_for(locale_of(request), _state(request)["types"])  # this language's
    hits = index.query(q, kind=kind, limit=size, offset=(page - 1) * size) if q else []
    total = index.count(q, kind=kind) if q else 0
    return render(
        request,
        "content/search.html",
        fragment="results",
        q=q,
        hits=hits,
        total=total,
        page=page,
        pages=max(1, math.ceil(total / size)),
    )


# --- public pages, found by path -------------------------------------------------------


def serve(request: Request) -> Response | None:
    """The fallback: an entry or a term at this path, or None."""
    db, _search, _storage = _bindings(request)
    state = _state(request)
    path = request.url.path
    old = _wordpress(request, db, state, path)
    if old is not None:
        return old
    if path == "/":
        home = state["settings"].get("home")
        if home:
            e = service.entry_by_path(db, home)
            if e is not None:
                return _entry_page(request, db, state, e)
        return _listing_page(request, db, state, None)
    registry, locale = state["types"], locale_of(request)
    query = f"?{request.url.query}" if request.url.query else ""
    # in this language, or the default's text standing in; another language's address
    # sends to this one's (a language switch, a shared link)
    e, elsewhere = translated.entry_at(db, registry, path, locale)
    if e is not None:
        return _entry_page(request, db, state, e)
    if elsewhere is None:
        term, elsewhere = translated.term_at(db, registry, path, locale)
        if term is not None:
            return _listing_page(request, db, state, term)
    if elsewhere is not None and elsewhere != path:
        return RedirectResponse(elsewhere + query, status_code=301)
    other = path[:-1] if path.endswith("/") else path + "/"
    if translated.entry_at(db, registry, other, locale) != (None, None) or translated.term_at(
        db, registry, other, locale
    ) != (None, None):
        return RedirectResponse(other + query, status_code=301)
    return None


def _wordpress(request: Request, db: Any, state: dict[str, Any], path: str) -> Response | None:
    """The addresses a WordPress site had besides its pages, sent where they are now:
    ?p=, ?page_id= (an entry by its old id), ?cat= (a category), ?s= (a search), a
    category's feed (/category/x/feed/, served), an entry's or the comments' feed, and
    the sign-in and admin addresses editors kept in their bookmarks."""
    q = request.query_params
    if path == "/":
        for key in ("p", "page_id"):
            if q.get(key, "").isdigit():
                e = service.entry_by_legacy(db, int(q[key]))
                if e is not None and e.status == "published":
                    return RedirectResponse(e.path, status_code=301)
        if q.get("cat", "").isdigit():
            t = service.term_by(db, "category", legacy_id=int(q["cat"]))
            if t is not None and t.path:
                return RedirectResponse(t.path, status_code=301)
        if "s" in q:
            from urllib.parse import urlencode  # noqa: PLC0415

            return RedirectResponse("/search?" + urlencode({"q": q["s"][:200]}), status_code=301)
        return None
    nest = request.app.state.nest
    if path in ("/wp-login.php", "/wp-admin", "/wp-admin/"):
        if path == "/wp-login.php":
            auth = next(
                (u.instance.route for u in nest.plan.units if u.name == "auth" and u.instance), None
            )
            target = f"{auth.rstrip('/')}/login" if auth else None
        else:
            target = nest.admin_root
        return RedirectResponse(target, status_code=301) if target else None
    if path == "/comments/feed/":
        return RedirectResponse("/feed/", status_code=301)
    if path.endswith("/feed/") and len(path) > len("/feed/"):
        base = path[: -len("feed/")]
        registry, locale = state["types"], locale_of(request)
        term, _elsewhere = translated.term_at(db, registry, base, locale)
        if term is not None:
            from nest_content.seo import feed_of  # noqa: PLC0415

            return feed_of(request, db, translated.show_terms(db, registry, [term], locale)[0])
        e, _elsewhere = translated.entry_at(db, registry, base, locale)
        if e is not None:  # an entry's comment feed: the entry itself
            return RedirectResponse(base, status_code=301)
    return None


def _say_where(request: Request, registry: Any, shown: Any, alternates: dict[str, Any]) -> None:
    """Tell the language layer where this page is in each language (hreflang), and when
    it is the original's text standing in for a missing translation."""
    if len(registry.languages) > 1:
        request.state.alternates = alternates
        if getattr(shown, "fallback", False):
            request.state.language_fallback = True


def _entry_page(request: Request, db: Any, state: dict[str, Any], e: Entry) -> Response:
    registry = state["types"]
    locale = locale_of(request)
    home = state["settings"].get("home") == e.path
    original = e
    e = translated.show_entries(db, registry, [e], locale)[0]
    _say_where(request, registry, e, translated.entry_alternates(db, registry, original, home))
    spec = registry.type(e.type)
    template = spec.template or f"content/{e.type}.html"
    env = request.app.state.nest.templates
    try:
        env.get_template(template)
    except Exception:  # noqa: BLE001
        template = "content/entry.html"

    def path_of(legacy: int) -> str | None:
        found = service.entry_by_legacy(db, legacy)
        return found.path if found is not None and found.status == "published" else None

    body = old_links(
        responsive_images(
            request.app.state.nest.shortcodes.expand(
                # cleaned when saved, and again here: a body that came in another way
                # (an import, a script, an old row) is never shown as it was sent
                embed_videos(sanitize(e.body or ""), translator(request)("Play the video")),
                Context(db, e, request),
            ),
            media_base(request),
        ),
        path_of,
        e.path,
    )
    nest = request.app.state.nest
    if nest.answered("gallery.spotlight"):
        # emphasized pictures framed and opening large, side by side a mini-gallery; with the
        # setting, every picture opens large (the gallery module's viewer)
        shown = nest.lookup(
            "gallery.spotlight",
            {
                "html": body,
                "all": bool(state["settings"].get("pictures_open_large")),
                "viewer": nest.asset("gallery", "lightbox.js"),
            },
        )
        if shown:
            body = shown["html"]
    return render(
        request,
        template,
        entry=e,
        spec=spec,
        terms=translated.show_term_groups(db, registry, service.terms_of(db, e.id), locale),
        children=translated.show_entries(db, registry, service.children(db, e.id), locale)
        if spec.hierarchical
        else [],
        body=Markup(body),
        # the featured image above the text, unless the text itself starts with it (as
        # imported WordPress posts often do: the same picture twice)
        show_featured=not _opens_with(body, e.featured),
        description=seo.summary(e),
        canonical="/" if home else e.path,
    )


_LINKED_IMAGE = re.compile(
    r'(<a\b[^>]*?\bhref=")([^"]*)("[^>]*>\s*<img\b[^>]*?(?:src|srcset)="\s*(/media/[^"?\s,]+))',
    re.I,
)
_OLD_PAGE = re.compile(r"[?&](?:p|attachment_id)=\d+|/attachment/", re.I)
_IP_HOST = re.compile(
    r'(\bhref=")https?://\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?(?:/[a-z0-9_-]+)?(?=[/"])', re.I
)


def old_links(html: str, path_of: Any = None, here: str = "") -> str:
    """What imported posts still link to on the old site (a bare IP, often with a folder:
    http://79.118.74.35/morlaca/?p=27, or this site's own ?p= addresses): an old post's
    number (``path_of``: the entry's address now) goes to that entry; a picture linked to
    its own post, or to an attachment page no longer there, opens the picture itself.
    Another site's ?p= pages are left as they are."""

    def target(href: str) -> str | None:
        m = re.search(r"[?&](?:p|page_id)=(\d+)", href)
        if m and path_of is not None:
            return path_of(int(m.group(1)))
        return None

    def own(href: str) -> bool:
        return href.startswith("/") or _IP_HOST.match(f'href="{href}"') is not None

    def picture(m: re.Match) -> str:
        href, file = m.group(2), m.group(4)
        if not own(href) or not _OLD_PAGE.search(href):
            return m.group(0)
        path = target(href)
        return m.group(1) + (path if path and path != here else file) + m.group(3)

    html = _LINKED_IMAGE.sub(picture, html)

    def link(m: re.Match) -> str:
        href = m.group(2)
        if own(href) and _OLD_PAGE.search(href):
            path = target(href)
            if path:
                return m.group(1) + path + '"'
        return m.group(0)

    html = re.sub(r'(<a\b[^>]*?\bhref=")([^"]*)"', link, html)
    return _IP_HOST.sub(r"\1", html)


def _opens_with(html: str, featured: str | None) -> bool:
    """Whether the text's first picture is the featured one."""
    if not featured:
        return False
    first = re.search(r"<img\b[^>]*>", html, re.I)
    return bool(first and featured.lstrip("/").split("?")[0] in first.group(0))


def _listing_page(request: Request, db: Any, state: dict[str, Any], term: Any) -> Response:
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    per_page = int(state["settings"].get("per_page"))
    types = [t for t, s in state["types"].types.items() if not s.hierarchical]
    entries, total = service.listing(
        db, types=types, term_id=term.id if term else None, page=page, per_page=per_page
    )
    registry, locale = state["types"], locale_of(request)
    entries = translated.show_entries(db, registry, entries, locale)
    if term is not None:
        original = term
        term = translated.show_terms(db, registry, [term], locale)[0]
        _say_where(request, registry, term, translated.term_alternates(db, registry, original))
    else:
        _say_where(request, registry, None, dict.fromkeys(registry.languages, "/"))
    return render(
        request,
        "content/listing.html",
        fragment="listing",
        term=term,
        entries=entries,
        page=page,
        pages=max(1, math.ceil(total / per_page)),
        total=total,
    )


# --- editing -----------------------------------------------------------------------


@admin.get("/")
def admin_home(
    request: Request, user: CurrentUser = Depends(editor), db: Database = bound(Database)
):
    registry = _state(request)["types"]
    sections = []
    for name, spec in registry.types.items():
        grouping = next((t for t in spec.taxonomies if registry.taxonomies[t].hierarchical), None)
        sections.append(
            {
                "name": name,
                "spec": spec,
                "grouping": grouping,
                "tree": [x for x in service.term_tree(db, grouping, name) if x[2]]
                if grouping
                else [],
                "loose": service.entries_of_type(db, name, per_page=1, without=grouping)[1]
                if grouping
                else 0,
            }
        )
    return render(
        request,
        "content/editor/home.html",
        types=registry.types,
        sections=sections,
        taxonomies=[(n, t, len(service.terms(db, n))) for n, t in registry.taxonomies.items()],
        counts=service.counts_by_type(db),
    )


# --- the media library (the editor's pictures) -------------------------------------


def _media_item(request: Request, m: Any) -> dict[str, Any]:
    from nest_media import media_url

    return {
        "key": m.key,
        "url": media_url(request, m.key),
        "thumb": media_url(request, m.key, 320),
        "alt": m.alt,
        "filename": m.filename,
        "content_type": m.content_type,
    }


@admin.get("/media.json")
def admin_media(
    request: Request,
    q: str = "",
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    items = service.media_list(db, q.strip()[:100])
    return JSONResponse({"items": [_media_item(request, m) for m in items]})


@admin.post("/media")
async def admin_upload(request: Request, user: CurrentUser = Depends(editor)):
    """A picture from the editor: checked by its bytes, at most media_max_mb, stored at
    uploads/<year>/<month>/<name>."""
    db, _search, storage = _bindings(request)
    t = translator(request)
    limit = int(_state(request)["settings"].get("media_max_mb")) * 2**20
    form = await request.form(max_files=1, max_fields=5)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": t("Choose a picture.")}, status_code=400)
    data = await upload.read(limit + 1)
    if len(data) > limit:
        return JSONResponse(
            {"error": t("A picture is at most {n} MB.", n=limit // 2**20)}, status_code=413
        )
    from nest_media import ImageError, clean_image

    try:  # read whole and written again: a real picture, without its camera's metadata
        data, kind = await run_in_threadpool(clean_image, data)
    except ImageError as e:
        return JSONResponse({"error": t(e.message, **e.params)}, status_code=415)
    key = await run_in_threadpool(service.upload_key, db, upload.filename or "", kind)
    m = await run_in_threadpool(
        service.add_media,
        db,
        storage,
        key,
        data,
        filename=(upload.filename or key.rsplit("/", 1)[-1])[:300],
        alt=str(form.get("alt", ""))[:300],
        content_type=kind,
        uploaded_by=user.id,
    )
    return JSONResponse(_media_item(request, m), status_code=201)


# --- categories and tags ------------------------------------------------------------


def _taxonomy_or_404(request: Request, taxonomy: str) -> Any:
    spec = _state(request)["types"].taxonomies.get(taxonomy)
    if spec is None:
        raise HTTPException(404)
    return spec


def _redirect_moves(request: Request, moves: list[tuple[str, str]], note: str) -> int:
    """Each moved address sends on to its new one (with the redirects module)."""
    nest = request.app.state.nest
    if not nest.answered("redirects.moved"):
        return 0
    done = 0
    for old, new in moves:
        if old and new and old != new:
            nest.lookup("redirects.moved", {"source": old, "target": new, "note": note})
            done += 1
    return done


def _types_using(request: Request, taxonomy: str) -> list[str]:
    return [n for n, t in _state(request)["types"].types.items() if taxonomy in t.taxonomies]


@admin.get("/taxonomies/{taxonomy}")
def admin_terms(
    request: Request,
    taxonomy: str,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    spec = _taxonomy_or_404(request, taxonomy)
    return render(
        request,
        "content/editor/terms.html",
        taxonomy=taxonomy,
        spec=spec,
        tree=service.term_tree(db, taxonomy),
        types=_types_using(request, taxonomy),
        values={"name": "", "slug": "", "parent_id": "", "description": ""},
        error=None,
    )


def _term_form(
    request: Request,
    db: Any,
    taxonomy: str,
    term: Any,
    values: dict,
    error: str | None = None,
    status: int = 200,
    posted=None,
):
    spec = _taxonomy_or_404(request, taxonomy)
    tree = service.term_tree(db, taxonomy)
    inside = set()
    if term is not None:
        with db.session() as s:
            inside = set(service.term_descendants(s, term.id))
    count = next((n for t, _d, n in tree if term is not None and t.id == term.id), 0)
    return render(
        request,
        "content/editor/term.html",
        status_code=status,
        taxonomy=taxonomy,
        spec=spec,
        term=term,
        values=values,
        parents=[(t, d) for t, d, _n in tree if t.id not in inside],
        count=count,
        error=error,
        posted=posted,
    )


@admin.get("/taxonomies/{taxonomy}/{term_id:int}")
def admin_term(
    request: Request,
    taxonomy: str,
    term_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    term = service.term_by_id(db, term_id)
    if term is None or term.taxonomy != taxonomy:
        raise HTTPException(404)
    values = {
        "name": term.name,
        "slug": term.slug,
        "parent_id": term.parent_id or "",
        "description": term.description,
    }
    return _term_form(request, db, taxonomy, term, values)


async def _save_term(request: Request, taxonomy: str, term_id: int | None) -> Response:
    db, index, _storage = _bindings(request)
    nest = request.app.state.nest
    t = translator(request)
    _taxonomy_or_404(request, taxonomy)
    form = await request.form()
    parent = str(form.get("parent_id", "")).strip()
    values = {
        "name": str(form.get("name", "")),
        "slug": str(form.get("slug", "")),
        "parent_id": int(parent) if parent.isdigit() else "",
        "description": str(form.get("description", "")),
    }
    term = service.term_by_id(db, term_id) if term_id else None
    try:
        problem = nest.lookup("seo.check", {"form": form}) or nest.lookup(
            "translations.check", {"subject": "content.term", "id": term_id or 0, "form": form}
        )
        if problem:
            raise ContentError(problem)
        saved, moves = await run_in_threadpool(
            service.save_term,
            db,
            index,
            _state(request)["types"],
            taxonomy,
            service.TermData(
                name=values["name"],
                slug=values["slug"],
                parent_id=values["parent_id"] or None,
                description=values["description"],
            ),
            term_id,
        )
    except ContentError as err:
        message = t(err.message, **err.params)
        toast(request, t("Not saved: {reason}", reason=message), "error")
        if term_id is None:
            return render(
                request,
                "content/editor/terms.html",
                status_code=400,
                taxonomy=taxonomy,
                spec=_taxonomy_or_404(request, taxonomy),
                tree=service.term_tree(db, taxonomy),
                types=_types_using(request, taxonomy),
                values=values,
                error=message,
            )
        return _term_form(request, db, taxonomy, term, values, message, 400, form)
    nest.lookup("seo.save", {"subject": f"content.term:{saved.id}", "form": form})
    await run_in_threadpool(
        nest.lookup, "translations.save", {"subject": "content.term", "id": saved.id, "form": form}
    )
    moved = _redirect_moves(request, moves, f"{taxonomy} {saved.slug}")
    if moved:
        toast(
            request,
            t.ngettext(
                "Saved; {n} old address now sends on to the new one.",
                "Saved; {n} old addresses now send on to the new ones.",
                moved,
            ),
        )
    else:
        toast(request, t("Saved."))
    target = admin_url(
        request,
        "content",
        f"taxonomies/{quote(taxonomy)}" + ("" if term_id is None else f"/{saved.id}"),
    )
    return RedirectResponse(target, status_code=303)


@admin.post("/taxonomies/{taxonomy}/new")
async def admin_term_create(request: Request, taxonomy: str, user: CurrentUser = Depends(editor)):
    return await _save_term(request, taxonomy, None)


@admin.post("/taxonomies/{taxonomy}/{term_id:int}")
async def admin_term_update(
    request: Request, taxonomy: str, term_id: int, user: CurrentUser = Depends(editor)
):
    return await _save_term(request, taxonomy, term_id)


@admin.post("/taxonomies/{taxonomy}/{term_id:int}/delete")
def admin_term_delete(
    request: Request,
    taxonomy: str,
    term_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    term = service.term_by_id(db, term_id)
    if term is None or term.taxonomy != taxonomy:
        raise HTTPException(404)
    moves = service.delete_term(db, index, _state(request)["types"], term_id)
    request.app.state.nest.lookup("seo.forget", f"content.term:{term_id}")
    _redirect_moves(request, moves, f"{taxonomy} {term.slug} deleted")
    toast(
        request,
        translator(request)("“{name}” is deleted; its entries stay, without it.", name=term.name),
    )
    return RedirectResponse(
        admin_url(request, "content", f"taxonomies/{quote(taxonomy)}"), status_code=303
    )


@admin.get("/entries/{entry_id:int}")
def admin_entry_by_id(
    request: Request,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """An entry's editor by its id alone (where another module links it: translations)."""
    e = service.entry(db, entry_id)
    if e is None:
        raise HTTPException(404)
    return RedirectResponse(
        admin_url(request, "content", f"{quote(e.type)}/{e.id}"), status_code=303
    )


@admin.get("/terms/{term_id:int}")
def admin_term_by_id(
    request: Request,
    term_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    t = service.term_by_id(db, term_id)
    if t is None:
        raise HTTPException(404)
    return RedirectResponse(
        admin_url(request, "content", f"taxonomies/{quote(t.taxonomy)}/{t.id}"), status_code=303
    )


@admin.get("/{type_name}")
def admin_list(
    request: Request,
    type_name: str,
    q: str = "",
    page: int = 1,
    category: str = "",
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """A type's entries, a category at a time: its categories beside the list, each with
    how many it holds, and those without one."""
    registry = _state(request)["types"]
    if type_name not in registry.types:
        raise HTTPException(404)
    spec = registry.types[type_name]
    # what the list is sorted by: the type's first hierarchical taxonomy (its categories)
    grouping = next(
        (t for t in spec.taxonomies if registry.taxonomies[t].hierarchical),
        spec.taxonomies[0] if spec.taxonomies else None,
    )
    term = None
    if grouping and category.isdigit():
        term = service.term_by_id(db, int(category))
        if term is None or term.taxonomy != grouping:
            term = None
    entries, total = service.entries_of_type(
        db,
        type_name,
        q=q.strip(),
        page=max(1, page),
        term_id=term.id if term else None,
        without=grouping if grouping and category == "none" else None,
    )
    tree = service.term_tree(db, grouping, type_name) if grouping else []
    nest = request.app.state.nest
    tr_states = (  # where each stands in the other languages, with the translations module
        nest.lookup(
            "translations.states", {"subject": "content.entry", "ids": [e.id for e in entries]}
        )
        if nest.answered("translations.states") and entries
        else None
    )
    everything = service.entries_of_type(db, type_name, per_page=1)[1]
    loose = (
        service.entries_of_type(db, type_name, per_page=1, without=grouping)[1] if grouping else 0
    )
    return render(
        request,
        "content/editor/list.html",
        fragment="rows",
        type_name=type_name,
        spec=spec,
        entries=entries,
        total=total,
        q=q,
        page=page,
        pages=max(1, math.ceil(total / 50)),
        trash_count=len(service.trashed(db, type_name)),
        grouping=grouping,
        grouping_spec=registry.taxonomies[grouping] if grouping else None,
        tree=tree,
        category=category if (term or category == "none") else "",
        current_term=term,
        everything=everything,
        loose=loose,
        tr_states=tr_states or None,
    )


def _form_context(
    request: Request,
    db: Any,
    type_name: str,
    values: dict[str, Any],
    entry: Entry | None,
    error: str | None = None,
) -> dict[str, Any]:
    registry = _state(request)["types"]
    spec = registry.types[type_name]
    return {
        "type_name": type_name,
        "spec": spec,
        "values": values,
        "entry": entry,
        "error": error,
        "statuses": STATUSES,
        "taxonomies": {t: (registry.taxonomies[t], service.terms(db, t)) for t in spec.taxonomies},
        "parents": service.entries_of_type(db, type_name, per_page=500)[0]
        if spec.hierarchical
        else [],
        "revisions": service.revisions(db, entry.id)[:10] if entry else [],
    }


def _values_of(e: Entry, terms: dict[str, list[Any]]) -> dict[str, Any]:
    return {
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "excerpt": e.excerpt,
        "body": e.body,
        "parent_id": e.parent_id or "",
        "featured": e.featured,
        "published_at": e.published_at.strftime("%Y-%m-%dT%H:%M") if e.published_at else "",
        "fields": dict(e.fields or {}),
        "terms": {t: [x.id for x in ts] for t, ts in terms.items()},
    }


@admin.get("/{type_name}/new")
def admin_new(
    request: Request,
    type_name: str,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    if type_name not in _state(request)["types"].types:
        raise HTTPException(404)
    values = {
        "title": "",
        "slug": "",
        "status": "draft",
        "excerpt": "",
        "body": "",
        "parent_id": "",
        "featured": "",
        "published_at": "",
        "fields": {},
        "terms": {},
    }
    wanted = request.query_params.get("category", "")
    if wanted.isdigit():  # "New" from a category's list: in that category
        t = service.term_by_id(db, int(wanted))
        if t is not None and t.taxonomy in _state(request)["types"].types[type_name].taxonomies:
            values["terms"] = {t.taxonomy: [t.id]}
    return render(
        request, "content/editor/edit.html", **_form_context(request, db, type_name, values, None)
    )


@admin.get("/{type_name}/{entry_id:int}")
def admin_edit(
    request: Request,
    type_name: str,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    e = service.entry(db, entry_id)
    if e is None or e.type != type_name:
        raise HTTPException(404)
    values = _values_of(e, service.terms_of(db, e.id))
    copy_of = None
    wanted = request.query_params.get("from_version", "")
    if wanted.isdigit() and e.status != service.TRASH:
        rev = service.revision(db, int(wanted))
        if rev is not None and rev.entry_id == e.id:
            values = _values_of_snapshot(db, rev.data, values)  # a copy to work on, unsaved
            copy_of = rev
    context = _form_context(request, db, type_name, values, e)
    return render(
        request,
        "content/editor/edit.html",
        copy_of=copy_of,
        authors=_authors(db, context["revisions"]),
        **context,
    )


def _authors(db: Any, revisions: list[Any]) -> dict[int, str]:
    from nest_auth import users_by_ids

    found = users_by_ids(db, [r.author_id for r in revisions if r.author_id])
    return {uid: (u.name or u.email) for uid, u in found.items()}


def _values_of_snapshot(db: Any, snap: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """A version's values, in the form's shape (its terms grouped by taxonomy)."""
    when = snap.get("published_at")
    groups: dict[str, list[int]] = {}
    for term_id in snap.get("terms") or []:
        t = service.term(db, term_id)
        if t is not None:
            groups.setdefault(t.taxonomy, []).append(t.id)
    return {
        **current,
        "title": snap.get("title", ""),
        "slug": snap.get("slug", ""),
        "status": snap.get("status") if snap.get("status") in STATUSES else "draft",
        "excerpt": snap.get("excerpt", ""),
        "body": snap.get("body", ""),
        "parent_id": snap.get("parent_id") or "",
        "featured": snap.get("featured", ""),
        "published_at": datetime.fromisoformat(when).strftime("%Y-%m-%dT%H:%M") if when else "",
        "fields": dict(snap.get("fields") or {}),
        "terms": groups,
    }


# --- versions -----------------------------------------------------------------------


def _version_or_404(db: Any, type_name: str, entry_id: int, revision_id: int) -> tuple[Any, Any]:
    e = service.entry(db, entry_id)
    rev = service.revision(db, revision_id)
    if e is None or e.type != type_name or rev is None or rev.entry_id != e.id:
        raise HTTPException(404)
    return e, rev


@admin.get("/{type_name}/{entry_id:int}/versions/{revision_id:int}")
def admin_version(
    request: Request,
    type_name: str,
    entry_id: int,
    revision_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """A version: as the page showed it, and what changed from it to the current one."""
    from nest_content.diff import field_changes, text_diff

    e, rev = _version_or_404(db, type_name, entry_id, revision_id)
    t = translator(request)
    spec = _state(request)["types"].types[type_name]
    snap = rev.data or {}
    current = service._snapshot(e, [x.id for ts in service.terms_of(db, e.id).values() for x in ts])
    names = lambda ids: [n.name for n in (service.term(db, i) for i in ids or []) if n]  # noqa: E731
    labels = {
        "title": t("Title"),
        "slug": t("Slug"),
        "status": t("Status"),
        "excerpt": t("Summary"),
        "featured": t("Featured image"),
        "published_at": t("Published"),
        "terms": t("Categories and tags"),
    }
    then = {**snap, "terms": names(snap.get("terms")), "status": t(snap.get("status") or "")}
    now = {
        **current,
        "terms": names(current.get("terms")),
        "status": t(current.get("status") or ""),
    }
    for name, f in spec.fields.items():
        labels[f"field:{name}"] = f.label or name
        then[f"field:{name}"] = (snap.get("fields") or {}).get(name)
        now[f"field:{name}"] = (current.get("fields") or {}).get(name)
    diff, changed_blocks = text_diff(
        snap.get("body") or "",
        e.body or "",
        picture=t("picture"),
        unchanged=lambda n: t.ngettext("{n} unchanged paragraph", "{n} unchanged paragraphs", n),
    )
    versions = service.revisions(db, e.id)
    return render(
        request,
        "content/editor/version.html",
        entry=e,
        spec=spec,
        type_name=type_name,
        rev=rev,
        snap=snap,
        author=_authors(db, [rev]).get(rev.author_id or 0, ""),
        preview=Markup(sanitize(snap.get("body") or "")),  # cleaned again: shown as HTML
        diff=diff,
        changed_blocks=changed_blocks,
        fields=field_changes(then, now, labels),
        newer=next((v for v in reversed(versions) if v.id > rev.id), None),
        older=next((v for v in versions if v.id < rev.id), None),
        in_trash=e.status == service.TRASH,
    )


@admin.post("/{type_name}/{entry_id:int}/versions/{revision_id:int}/restore")
async def admin_restore_version(
    request: Request,
    type_name: str,
    entry_id: int,
    revision_id: int,
    user: CurrentUser = Depends(editor),
):
    db, index, _storage = _bindings(request)
    e, rev = _version_or_404(db, type_name, entry_id, revision_id)
    form = await request.form()
    only_body = str(form.get("what", "all")) == "text"
    t = translator(request)
    try:
        await run_in_threadpool(
            service.restore_revision,
            db,
            index,
            _state(request)["types"],
            entry_id,
            revision_id,
            author_id=user.id,
            only_body=only_body,
        )
    except ContentError as err:
        toast(request, t(err.message, **err.params), "error")
        return RedirectResponse(
            admin_url(request, "content", f"{quote(type_name)}/{entry_id}"), status_code=303
        )
    when = rev.created_at.strftime("%d.%m.%Y %H:%M")
    toast(
        request,
        t("The text of the version until {when} is back; the rest stays as it was.", when=when)
        if only_body
        else t(
            "The version until {when} is back; the one it replaced is kept with the others.",
            when=when,
        ),
    )
    return RedirectResponse(
        admin_url(request, "content", f"{quote(type_name)}/{entry_id}"), status_code=303
    )


# --- the trash ----------------------------------------------------------------------


def _purge(request: Request, db: Any, index: Any) -> None:
    days = int(_state(request)["settings"].get("trash_days"))
    if days > 0:
        service.empty_trash(db, index, older_than_days=days)


@admin.get("/{type_name}/trash")
def admin_trash(
    request: Request,
    type_name: str,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    registry = _state(request)["types"]
    if type_name not in registry.types:
        raise HTTPException(404)
    _purge(request, db, index)
    return render(
        request,
        "content/editor/trash.html",
        type_name=type_name,
        spec=registry.types[type_name],
        entries=service.trashed(db, type_name),
        days=int(_state(request)["settings"].get("trash_days")),
    )


@admin.post("/{type_name}/{entry_id:int}/untrash")
def admin_untrash(
    request: Request,
    type_name: str,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    e = service.untrash_entry(db, index, entry_id, _state(request)["types"])
    if e is None or e.type != type_name:
        raise HTTPException(404)
    toast(request, translator(request)("“{title}” is back from the trash.", title=e.title))
    return RedirectResponse(
        admin_url(request, "content", f"{quote(type_name)}/{e.id}"), status_code=303
    )


@admin.post("/{type_name}/{entry_id:int}/purge")
def admin_purge(
    request: Request,
    type_name: str,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    e = service.entry(db, entry_id)
    if e is None or e.type != type_name or e.status != service.TRASH:
        raise HTTPException(404)  # only what is in the trash is deleted for good
    service.delete_entry(db, index, entry_id)
    request.app.state.nest.lookup("seo.forget", f"content.entry:{entry_id}")
    toast(request, translator(request)("Deleted for good."))
    return RedirectResponse(
        admin_url(request, "content", f"{quote(type_name)}/trash"), status_code=303
    )


@admin.post("/{type_name}/trash/empty")
def admin_empty_trash(
    request: Request,
    type_name: str,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    gone = 0
    for e in service.trashed(db, type_name):
        service.delete_entry(db, index, e.id)
        request.app.state.nest.lookup("seo.forget", f"content.entry:{e.id}")
        gone += 1
    t = translator(request)
    toast(request, t("The trash is empty ({n} deleted for good).", n=gone))
    return RedirectResponse(
        admin_url(request, "content", f"{quote(type_name)}/trash"), status_code=303
    )


async def _save(
    request: Request, type_name: str, user: CurrentUser, existing_id: int | None
) -> Response:
    db, index, _storage = _bindings(request)
    registry = _state(request)["types"]
    if type_name not in registry.types:
        raise HTTPException(404)
    form = await request.form()
    spec = registry.types[type_name]
    published = str(form.get("published_at", "")).strip()
    try:
        when = datetime.fromisoformat(published) if published else None
    except ValueError:
        when = None
    parent = str(form.get("parent_id", "")).strip()
    values = {
        "title": str(form.get("title", "")),
        "slug": str(form.get("slug", "")),
        "status": str(form.get("status", "draft")),
        "excerpt": str(form.get("excerpt", "")),
        "body": str(form.get("body", "")),
        "featured": str(form.get("featured", "")).strip(),
        "parent_id": int(parent) if parent.isdigit() else None,
        "published_at": published,
        "fields": {name: str(form.get(f"field_{name}", "")) for name in spec.fields},
        "terms": {
            t: [int(x) for x in form.getlist(f"terms_{t}") if str(x).isdigit()]
            for t in spec.taxonomies
        },
    }
    for name, f in spec.fields.items():
        if f.type == "boolean":
            values["fields"][name] = bool(form.get(f"field_{name}"))
    data = EntryData(
        type=type_name,
        title=values["title"],
        slug=values["slug"],
        status=values["status"],
        excerpt=values["excerpt"],
        body=values["body"],
        fields=values["fields"],
        terms=values["terms"],
        parent_id=values["parent_id"],
        featured=values["featured"],
        published_at=when,
        author_id=user.id,
    )
    nest = request.app.state.nest
    try:
        # the seo fields, if the seo module put them in the form, are checked first: a page
        # is saved whole or not at all
        seo_problem = nest.lookup("seo.check", {"form": form}) or nest.lookup(
            "translations.check", {"subject": "content.entry", "id": existing_id or 0, "form": form}
        )
        if seo_problem:
            raise ContentError(seo_problem)
        e = await run_in_threadpool(
            service.save_entry, db, index, registry, data, existing_id=existing_id
        )
        await run_in_threadpool(
            nest.lookup, "seo.save", {"subject": f"content.entry:{e.id}", "form": form}
        )
        # the other languages' text, after the original's (their source)
        await run_in_threadpool(
            nest.lookup, "translations.save", {"subject": "content.entry", "id": e.id, "form": form}
        )
    except ContentError as err:
        message = translator(request)(err.message, **err.params)
        toast(request, translator(request)("Not saved: {reason}", reason=message), "error")
        entry = await run_in_threadpool(service.entry, db, existing_id) if existing_id else None
        context = await run_in_threadpool(
            _form_context, request, db, type_name, values, entry, message
        )
        return render(
            request,
            "content/editor/edit.html",
            fragment="form",
            status_code=200 if is_htmx(request) else 400,
            posted=form,  # the seo fields show what was typed
            **context,
        )
    t = translator(request)
    toast(request, t("Saved.") if e.status != "published" else t("Saved and published."))
    target = admin_url(request, "content", f"{quote(type_name)}/{e.id}?saved=1")
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


@admin.post("/{type_name}/new")
async def admin_create(request: Request, type_name: str, user: CurrentUser = Depends(editor)):
    return await _save(request, type_name, user, None)


@admin.post("/{type_name}/{entry_id:int}")
async def admin_update(
    request: Request, type_name: str, entry_id: int, user: CurrentUser = Depends(editor)
):
    return await _save(request, type_name, user, entry_id)


@admin.post("/{type_name}/{entry_id:int}/delete")
def admin_delete(
    request: Request,
    type_name: str,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    e = service.trash_entry(db, index, entry_id, author_id=user.id)
    if e is None or e.type != type_name:
        raise HTTPException(404)
    toast(
        request,
        translator(request)(
            "“{title}” is in the trash; it can be brought back from there.", title=e.title
        ),
    )
    return RedirectResponse(admin_url(request, "content", quote(type_name)), status_code=303)
