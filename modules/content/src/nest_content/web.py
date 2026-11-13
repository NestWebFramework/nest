"""The content module over HTTP.

Public pages are not routes: an entry or a term is found by its stored path
when no route matched (a fallback), so a site keeps whatever addresses it had
(/istorie/biserica-din-morlaca/) without a catch-all that would shadow other
modules. Media is served from nest.storage. Editors work under /admin/content.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, require_role
from nest_db import Database
from nest_search import Search
from starlette.concurrency import run_in_threadpool

from nest import bound, is_htmx, render, translator
from nest.host import module_state
from nest_content import service
from nest_content.html import link_list
from nest_content.models import STATUSES, Entry
from nest_content.service import KIND, ContentError, EntryData

router = APIRouter()
editor = require_role("editor")


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "content")


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


# --- search ------------------------------------------------------------------------


@router.get("/search")
def search(request: Request, q: str = "", page: int = 1, index: Search = bound(Search)):
    q = q.strip()[:200]
    size = 20
    page = max(1, min(page, 500))
    hits = index.query(q, kind=KIND, limit=size, offset=(page - 1) * size) if q else []
    total = index.count(q, kind=KIND) if q else 0
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
    if path == "/":
        if request.query_params.get("p", "").isdigit():  # WordPress's ?p=123
            e = service.entry_by_legacy(db, int(request.query_params["p"]))
            if e is not None and e.status == "published":
                return RedirectResponse(e.path, status_code=301)
        home = state["settings"].get("home")
        if home:
            e = service.entry_by_path(db, home)
            if e is not None:
                return _entry_page(request, db, state, e)
        return _listing_page(request, db, state, None)
    e = service.entry_by_path(db, path)
    if e is not None:
        return _entry_page(request, db, state, e)
    term = service.term_by_path(db, path)
    if term is not None:
        return _listing_page(request, db, state, term)
    other = path[:-1] if path.endswith("/") else path + "/"
    if service.entry_by_path(db, other) or service.term_by_path(db, other):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(other + query, status_code=301)
    return None


def _entry_page(request: Request, db: Any, state: dict[str, Any], e: Entry) -> Response:
    registry = state["types"]
    spec = registry.type(e.type)
    template = spec.template or f"content/{e.type}.html"
    env = request.app.state.nest.templates
    try:
        env.get_template(template)
    except Exception:  # noqa: BLE001
        template = "content/entry.html"
    return render(
        request,
        template,
        entry=e,
        spec=spec,
        terms=service.terms_of(db, e.id),
        children=service.children(db, e.id) if spec.hierarchical else [],
        body=request.app.state.nest.shortcodes.expand(e.body, Context(db, e, request)),
    )


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


@router.get("/admin/content")
def admin_home(
    request: Request, user: CurrentUser = Depends(editor), db: Database = bound(Database)
):
    return render(
        request,
        "content/editor/home.html",
        types=_state(request)["types"].types,
        counts=service.counts_by_type(db),
    )


@router.get("/admin/content/{type_name}")
def admin_list(
    request: Request,
    type_name: str,
    q: str = "",
    page: int = 1,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    registry = _state(request)["types"]
    if type_name not in registry.types:
        raise HTTPException(404)
    entries, total = service.entries_of_type(db, type_name, q=q.strip(), page=max(1, page))
    return render(
        request,
        "content/editor/list.html",
        fragment="rows",
        type_name=type_name,
        spec=registry.types[type_name],
        entries=entries,
        total=total,
        q=q,
        page=page,
        pages=max(1, math.ceil(total / 50)),
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


@router.get("/admin/content/{type_name}/new")
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
    return render(
        request, "content/editor/edit.html", **_form_context(request, db, type_name, values, None)
    )


@router.get("/admin/content/{type_name}/{entry_id:int}")
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
    return render(
        request, "content/editor/edit.html", **_form_context(request, db, type_name, values, e)
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
    try:
        e = await run_in_threadpool(
            service.save_entry, db, index, registry, data, existing_id=existing_id
        )
    except ContentError as err:
        message = translator(request)(err.message, **err.params)
        entry = await run_in_threadpool(service.entry, db, existing_id) if existing_id else None
        context = await run_in_threadpool(
            _form_context, request, db, type_name, values, entry, message
        )
        return render(
            request,
            "content/editor/edit.html",
            fragment="form",
            status_code=200 if is_htmx(request) else 400,
            **context,
        )
    target = f"/admin/content/{quote(type_name)}/{e.id}?saved=1"
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


@router.post("/admin/content/{type_name}/new")
async def admin_create(request: Request, type_name: str, user: CurrentUser = Depends(editor)):
    return await _save(request, type_name, user, None)


@router.post("/admin/content/{type_name}/{entry_id:int}")
async def admin_update(
    request: Request, type_name: str, entry_id: int, user: CurrentUser = Depends(editor)
):
    return await _save(request, type_name, user, entry_id)


@router.post("/admin/content/{type_name}/{entry_id:int}/delete")
def admin_delete(
    request: Request,
    type_name: str,
    entry_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    index: Search = bound(Search),
):
    service.delete_entry(db, index, entry_id)
    return RedirectResponse(f"/admin/content/{quote(type_name)}", status_code=303)
