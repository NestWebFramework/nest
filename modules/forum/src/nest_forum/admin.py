"""The forum in the admin panel: its boards; moderation happens in the topics themselves."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from nest_auth import CurrentUser, require_role
from nest_db import Database

from nest import bound, render, translator
from nest.host import module_state
from nest_forum import service

admin = APIRouter()
keeper = require_role("moderator")  # who may see the overview


@admin.get("/")
def overview(
    request: Request,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    _ = translator(request)
    base = module_state(request, "forum").get("url", "")
    rows = service.boards(db)
    return render(
        request,
        "admin/overview.html",
        title=_("Forum"),
        intro=_("Moderators pin, lock and hide in the topics themselves."),
        facts=[
            (_("boards"), len(rows)),
            (_("topics"), sum(r.topics for r in rows)),
            (_("posts"), sum(r.posts for r in rows)),
        ],
        head=[_("Board"), _("Topics"), _("Posts")],
        rows=[
            [{"text": r.board.title, "href": f"{base}/{r.board.slug}/"}, r.topics, r.posts]
            for r in rows
        ],
        empty=_("No board yet."),
    )
