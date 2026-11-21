"""The forum in the admin panel: its boards as a tree; boards added (at the first level or in
another board, to any depth), renamed, put away in the archive or taken out, and deleted;
a board's topics archived or deleted. What happens to a board happens to every board in it:
an archived board's boards are read only too, a deleted board takes them, their topics and
their posts with it (after a page that says how much). Moderators pin, lock and hide in the
topics themselves."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from nest_db import Database

from nest import admin_url, bound, render, translator
from nest.host import module_state
from nest_forum import service

admin = APIRouter()
keeper = require_role("moderator")  # who may see the boards and change them


def _as_tree(rows: list) -> list[tuple[int, Any]]:
    """The boards in their nesting order, each with its depth (a board under the one it is in)."""
    kids: dict = {}
    for r in rows:
        kids.setdefault(r.board.parent_id, []).append(r)
    out: list[tuple[int, Any]] = []

    def walk(parent: Any, depth: int, put_away: bool) -> None:
        for r in kids.get(parent, []):
            r.put_away = put_away or r.board.archived  # archived, itself or by a board it is in
            out.append((depth, r))
            if depth < 32:
                walk(r.board.id, depth + 1, r.put_away)

    walk(None, 0, False)
    return out


def _here(request: Request) -> str:
    return admin_url(request, "forum")


def _base(request: Request) -> str:
    return module_state(request, "forum").get("url", "")


def _board(db: Any, slug: str) -> Any:
    b = service.board(db, slug)
    if b is None:
        raise HTTPException(404)
    return b


def _page(request: Request, db: Any, *, error: str | None = None, status_code: int = 200):
    _ = translator(request)
    rows = _as_tree(service.boards(db, scoped=True))
    return render(
        request,
        "forum/admin.html",
        status_code=status_code,
        title=_("Forum"),
        rows=rows,
        topics=sum(r.topics for _d, r in rows),
        posts=sum(r.posts for _d, r in rows),
        base=_base(request),
        here=_here(request),
        error=error,
    )


@admin.get("/")
def overview(request: Request, user: CurrentUser = Depends(keeper), db: Database = bound(Database)):
    return _page(request, db)


@admin.post("/boards")
def add_board(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    parent: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    """A board of the forum's own (no parent), or a board in another (it takes its scope)."""
    _ = translator(request)
    title = title.strip()[:200]
    if not title:
        return _page(request, db, error=_("A board needs a title."), status_code=400)
    inside = _board(db, parent) if parent else None
    if inside is not None and service.archived_in(db, inside):
        return _page(request, db, error=_("This board is closed."), status_code=400)
    service.ensure_board(
        db,
        title,
        slug=f"{inside.slug}-{title}" if inside is not None else title,
        description=description.strip()[:2000],
        parent=inside,
    )
    return RedirectResponse(_here(request) + "/", status_code=303)


@admin.get("/boards/{slug}")
def board_page(
    request: Request,
    slug: str,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
    error: str | None = None,
):
    """A board: its name and place, its boards, its topics (open and archived), and what
    can be done to them."""
    _ = translator(request)
    b = _board(db, slug)
    open_topics, _n = service.topics(db, b.id, page=1, per_page=500, include_hidden=True)
    put_away, _m = service.topics(
        db, b.id, page=1, per_page=500, include_hidden=True, archived=True
    )
    return render(
        request,
        "forum/admin_board.html",
        title=b.title,
        board=b,
        trail=service.trail(db, b),
        archived=service.archived_in(db, b),
        children=service.boards(db, parent_id=b.id),
        topics=open_topics + put_away,
        base=_base(request),
        here=_here(request),
        error=error,
    )


@admin.post("/boards/{slug}")
def save_board(
    request: Request,
    slug: str,
    title: str = Form(""),
    description: str = Form(""),
    position: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    _ = translator(request)
    b = _board(db, slug)
    title = title.strip()[:200]
    if not title:
        return board_page(request, slug, user, db, error=_("A board needs a title."))
    try:
        at = int(position) if position.strip() else None
    except ValueError:
        at = None
    service.update_board(db, b.id, title=title, description=description.strip()[:2000], position=at)
    return RedirectResponse(f"{_here(request)}/boards/{b.slug}", status_code=303)


@admin.post("/boards/{slug}/archive")
def archive_board(
    request: Request,
    slug: str,
    archived: str = Form("1"),
    back: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    """Put a board away, with every board in it (read, never written), or take it out."""
    b = _board(db, slug)
    service.archive_board(db, b.id, archived == "1")
    to = f"{_here(request)}/boards/{b.slug}" if back == "board" else f"{_here(request)}/"
    return RedirectResponse(to, status_code=303)


@admin.get("/boards/{slug}/delete")
def confirm_board_delete(
    request: Request, slug: str, user: CurrentUser = Depends(keeper), db: Database = bound(Database)
):
    _ = translator(request)
    b = _board(db, slug)
    return render(
        request,
        "forum/admin_delete.html",
        title=_("Delete a board"),
        what=b.title,
        reach=service.reach(db, b.id),
        action=f"{_here(request)}/boards/{b.slug}/delete",
        back=f"{_here(request)}/boards/{b.slug}",
        here=_here(request),
    )


@admin.post("/boards/{slug}/delete")
def delete_board(
    request: Request, slug: str, user: CurrentUser = Depends(keeper), db: Database = bound(Database)
):
    """The board, every board in it, their topics and posts: gone."""
    b = _board(db, slug)
    service.delete_board(db, b.id)
    up = service.board_by_id(db, b.parent_id) if b.parent_id else None
    to = f"{_here(request)}/boards/{up.slug}" if up is not None else f"{_here(request)}/"
    return RedirectResponse(to, status_code=303)


def _topic(db: Any, topic_id: int) -> Any:
    t = service.topic(db, topic_id)
    if t is None:
        raise HTTPException(404)
    return t


@admin.post("/topics/{topic_id:int}/archive")
def archive_topic(
    request: Request,
    topic_id: int,
    archived: str = Form("1"),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    t = _topic(db, topic_id)
    service.moderate_topic(db, t.id, "archive" if archived == "1" else "unarchive")
    b = service.board_by_id(db, t.board_id)
    return RedirectResponse(f"{_here(request)}/boards/{b.slug}", status_code=303)


@admin.get("/topics/{topic_id:int}/delete")
def confirm_topic_delete(
    request: Request,
    topic_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    _ = translator(request)
    t = _topic(db, topic_id)
    b = service.board_by_id(db, t.board_id)
    return render(
        request,
        "forum/admin_delete.html",
        title=_("Delete a topic"),
        what=t.title,
        reach={"boards": 0, "topics": 1, "posts": t.posts},
        action=f"{_here(request)}/topics/{t.id}/delete",
        back=f"{_here(request)}/boards/{b.slug}",
        here=_here(request),
    )


@admin.post("/topics/{topic_id:int}/delete")
def delete_topic(
    request: Request,
    topic_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    t = _topic(db, topic_id)
    service.delete_topic(db, t.id)
    b = service.board_by_id(db, t.board_id)
    return RedirectResponse(f"{_here(request)}/boards/{b.slug}", status_code=303)
