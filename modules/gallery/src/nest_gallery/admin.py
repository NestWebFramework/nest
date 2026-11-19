"""The galleries in the admin panel: every album and gallery, and an editor for each.

The editor changes a collection's title, description, cover and whether it is shown,
and each photo's alt text (what a reader who cannot see it, and a search engine, is
told) and caption; with the seo module, the collection's search and sharing fields too.
Photos come in with an import; they are described here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from nest_db import Database
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, render, toast, translator
from nest.host import module_state
from nest_gallery import service
from nest_gallery.models import Collection, Photo

admin = APIRouter()
keeper = require_role("editor")


@admin.get("/")
def overview(
    request: Request,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    _ = translator(request)
    base = module_state(request, "gallery").get("url", "")
    with db.session() as s:
        counts = dict(
            s.execute(select(Photo.collection_id, func.count()).group_by(Photo.collection_id)).all()
        )
        albums = list(
            s.scalars(
                select(Collection)
                .order_by(Collection.parent_id.is_not(None), Collection.position, Collection.title)
                .limit(500)
            )
        )
    return render(
        request,
        "admin/overview.html",
        title=_("Galleries"),
        intro=_("Albums come in with a site's import; open one to describe it and its photos."),
        facts=[(_("albums"), len(albums)), (_("photos"), sum(counts.values()))],
        head=[_("Album"), _("Photos"), _("Page")],
        rows=[
            [
                {
                    "text": a.title + ("" if a.published else f" ({_('hidden')})"),
                    "href": admin_url(request, "gallery", str(a.id)),
                },
                counts.get(a.id, 0),
                {"text": _("View"), "href": f"{base}/{a.slug}/"},
            ]
            for a in albums
        ],
        empty=_("No album yet."),
    )


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
    base = module_state(request, "gallery").get("url", "")
    return render(
        request,
        "gallery/editor.html",
        status_code=status,
        collection=c,
        photos=service.photos(db, c.id),
        children=service.cards(db, c.id),
        public=f"{base}/{c.slug}/",
        error=error,
        posted=posted,
    )


@admin.post("/{collection_id:int}")
async def save(request: Request, collection_id: int, user: CurrentUser = Depends(keeper)):
    db = request.app.state.nest.bindings.get("nest.db")
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
    problem = nest.lookup("seo.check", {"form": form})
    if problem:
        toast(request, t("Not saved: {reason}", reason=t(problem)), "error")
        return _page(request, db, c, t(problem), form, 400)
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
    except ValueError as e:
        toast(request, t("Not saved: {reason}", reason=t(str(e))), "error")
        return _page(request, db, c, t(str(e)), form, 400)
    nest.lookup("seo.save", {"subject": f"gallery.collection:{collection_id}", "form": form})
    toast(request, t("Saved."))
    return RedirectResponse(admin_url(request, "gallery", str(collection_id)), status_code=303)
