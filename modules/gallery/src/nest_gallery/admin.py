"""The galleries in the admin panel: every album and gallery as a tree, new ones, and an
editor for each.

The editor changes a collection's title, address, album (where it is: an album is a
gallery of galleries), description, cover and whether it is shown; it takes new photos
(uploaded: checked by their bytes, at most upload_max_mb each), puts them in order,
removes them, and holds each photo's alt text (what a reader who cannot see it, and a
search engine, is told) and caption; with the seo module, the collection's search and
sharing fields too. A gallery deleted takes its photos (their files stay, an article may
show them) and leaves its own galleries to its album.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from nest_auth import CurrentUser, require_role
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, render, toast, translator
from nest.host import module_state
from nest_gallery import service
from nest_gallery.models import Collection
from nest_gallery.service import GalleryError

admin = APIRouter()
keeper = require_role("editor")


def _base(request: Request) -> str:
    return module_state(request, "gallery").get("url", "")


def _bindings(request: Request) -> tuple[Any, Any]:
    b = request.app.state.nest.bindings
    return b.get("nest.db"), b.get("nest.storage")


def _limit(request: Request) -> int:
    return int(module_state(request, "gallery")["settings"].get("upload_max_mb")) * 2**20


def _message(request: Request, e: GalleryError) -> str:
    return translator(request)(e.message, **e.params)


@admin.get("/")
def overview(request: Request, user: CurrentUser = Depends(keeper), db: Database = bound(Database)):
    rows = service.tree(db)
    return render(
        request,
        "gallery/admin.html",
        rows=rows,
        photos=sum(n for _c, _d, n, _k in rows),
        parents=[(c, d) for c, d, _n, _k in rows],
        base=_base(request),
    )


@admin.post("/new")
async def create(request: Request, user: CurrentUser = Depends(keeper)):
    db, _storage = _bindings(request)
    form = await request.form()
    parent = str(form.get("parent_id", "")).strip()
    try:
        c = await run_in_threadpool(
            service.create,
            db,
            str(form.get("title", "")),
            int(parent) if parent.isdigit() else None,
        )
    except GalleryError as e:
        toast(
            request,
            translator(request)("Not saved: {reason}", reason=_message(request, e)),
            "error",
        )
        return RedirectResponse(admin_url(request, "gallery"), status_code=303)
    toast(request, translator(request)("“{title}” is made; add its photos.", title=c.title))
    return RedirectResponse(admin_url(request, "gallery", str(c.id)), status_code=303)


@admin.get("/{collection_id:int}")
def edit(
    request: Request,
    collection_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    c = service.by_id(db, collection_id)
    if c is None:
        raise HTTPException(404)
    return _page(request, db, c)


def _page(
    request: Request,
    db: Database,
    c: Collection,
    error: str | None = None,
    posted=None,
    status: int = 200,
):
    rows = service.tree(db)
    inside = {c.id}  # where it cannot go: itself, and every gallery under it
    for row, _depth, _n, _k in rows:
        if row.parent_id in inside:
            inside.add(row.id)
    return render(
        request,
        "gallery/editor.html",
        status_code=status,
        collection=c,
        photos=service.photos(db, c.id),
        children=service.cards(db, c.id),
        parents=[(row, d) for row, d, _n, _k in rows if row.id not in inside],
        public=f"{_base(request)}/{c.slug}/",
        limit_mb=_limit(request) // 2**20,
        error=error,
        posted=posted,
    )


def _order(form: Any) -> list[int]:
    """The photos' order the form gives (each row's hidden "order"), with a row moved up
    or down by its button ("move": "<id>:up")."""
    order = [int(x) for x in form.getlist("order") if str(x).isdigit()]
    move = str(form.get("move", ""))
    pid, _, way = move.partition(":")
    if pid.isdigit() and int(pid) in order:
        i = order.index(int(pid))
        j = i - 1 if way == "up" else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
    return order


@admin.post("/{collection_id:int}")
async def save(request: Request, collection_id: int, user: CurrentUser = Depends(keeper)):
    db, _storage = _bindings(request)
    nest = request.app.state.nest
    t = translator(request)
    c = service.by_id(db, collection_id)
    if c is None:
        raise HTTPException(404)
    form = await request.form()
    texts: dict[int, tuple[str, str]] = {}
    for key in form:
        if key.startswith("alt_") and key[4:].isdigit():
            pid = int(key[4:])
            texts[pid] = (str(form.get(key, "")), str(form.get(f"caption_{pid}", "")))
    remove = {int(x) for x in form.getlist("remove") if str(x).isdigit()}
    problem = nest.lookup("seo.check", {"form": form}) or nest.lookup(
        "translations.check", {"subject": "gallery.collection", "id": collection_id, "form": form}
    )
    if problem:
        toast(request, t("Not saved: {reason}", reason=t(problem)), "error")
        return _page(request, db, c, t(problem), form, 400)
    parent = str(form.get("parent_id", "")).strip()
    try:
        await run_in_threadpool(
            service.update,
            db,
            collection_id,
            title=str(form.get("title", "")),
            description=str(form.get("description", "")),
            is_published=bool(form.get("published")),
            cover=str(form.get("cover", "")),
            photo_texts=texts,
        )
        await run_in_threadpool(
            service.move, db, collection_id, int(parent) if parent.isdigit() else None
        )
        if str(form.get("slug", "")).strip() and form.get("slug") != c.slug:
            await run_in_threadpool(service.set_slug, db, collection_id, str(form.get("slug")))
        removed = await run_in_threadpool(service.arrange, db, collection_id, _order(form), remove)
    except (GalleryError, ValueError) as e:
        message = _message(request, e) if isinstance(e, GalleryError) else t(str(e))
        toast(request, t("Not saved: {reason}", reason=message), "error")
        return _page(request, db, c, message, form, 400)
    nest.lookup("seo.save", {"subject": f"gallery.collection:{collection_id}", "form": form})
    nest.lookup(
        "translations.save", {"subject": "gallery.collection", "id": collection_id, "form": form}
    )
    if form.get("move"):  # a photo moved by its button: back to it
        pid = str(form.get("move")).split(":")[0]
        return RedirectResponse(
            admin_url(request, "gallery", f"{collection_id}#photo-{pid}"), status_code=303
        )
    toast(
        request,
        t.ngettext("Saved; {n} photo removed.", "Saved; {n} photos removed.", removed)
        if removed
        else t("Saved."),
    )
    return RedirectResponse(admin_url(request, "gallery", str(collection_id)), status_code=303)


@admin.post("/{collection_id:int}/photos")
async def upload(request: Request, collection_id: int, user: CurrentUser = Depends(keeper)):
    """Photos into a gallery, one or many; JSON for the page's script (one file a request,
    its progress shown), else back to the editor with what was added."""
    db, storage = _bindings(request)
    t = translator(request)
    if service.by_id(db, collection_id) is None:
        raise HTTPException(404)
    limit = _limit(request)
    form = await request.form(max_files=50, max_fields=10)
    added, problems = [], []
    for item in form.getlist("files"):
        if not hasattr(item, "read"):
            continue
        name = (getattr(item, "filename", "") or "")[:200]
        data = await item.read(limit + 1)
        try:
            p = await run_in_threadpool(
                service.add_photo, db, storage, collection_id, name, data, limit, user.id
            )
        except GalleryError as e:
            problems.append(f"{name}: {_message(request, e)}")
            continue
        added.append({"id": p.id, "key": p.key, "name": name})
    if "application/json" in request.headers.get("accept", ""):
        status = 200 if added or not problems else 400
        return JSONResponse({"added": added, "problems": problems}, status_code=status)
    if added:
        toast(request, t.ngettext("{n} photo added.", "{n} photos added.", len(added)))
    for p in problems[:5]:
        toast(request, p, "error")
    return RedirectResponse(
        admin_url(request, "gallery", f"{collection_id}#photos"), status_code=303
    )


@admin.post("/{collection_id:int}/delete")
async def delete(
    request: Request, collection_id: int, user: CurrentUser = Depends(keeper)
) -> Response:
    db, _storage = _bindings(request)
    nest = request.app.state.nest
    form = await request.form()
    c = service.by_id(db, collection_id)
    if c is None:
        raise HTTPException(404)
    t = translator(request)
    if str(form.get("confirm", "")).strip() != c.title:
        toast(request, t("Type the gallery's title to delete it."), "error")
        return RedirectResponse(
            admin_url(request, "gallery", f"{collection_id}#delete"), status_code=303
        )
    gone = await run_in_threadpool(service.remove_collection, db, collection_id)
    nest.lookup("seo.forget", f"gallery.collection:{collection_id}")
    title = gone.title if gone else c.title
    toast(request, t("“{title}” is deleted; its galleries moved up to its album.", title=title))
    return RedirectResponse(admin_url(request, "gallery"), status_code=303)
