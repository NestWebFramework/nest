"""The galleries in the admin panel: an overview of the albums and their photos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from nest_auth import CurrentUser, require_role
from nest_db import Database
from sqlalchemy import func, select

from nest import bound, render, translator
from nest.host import module_state
from nest_gallery.models import Collection, Photo

admin = APIRouter()
keeper = require_role("editor")  # who may see the overview


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
        intro=_("Albums come in with a site's import; here, how many and what they hold."),
        facts=[(_("albums"), len(albums)), (_("photos"), sum(counts.values()))],
        head=[_("Album"), _("Photos")],
        rows=[
            [{"text": a.title, "href": f"{base}/{a.slug}/"}, counts.get(a.id, 0)] for a in albums
        ],
        empty=_("No album yet."),
    )
