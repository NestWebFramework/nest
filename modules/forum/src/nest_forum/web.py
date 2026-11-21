"""The forum over HTTP; new replies reach every open copy of the topic over SSE."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, current_user, known_as, require_role, require_user, users_by_ids
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, is_htmx, render, translator
from nest.host import module_state
from nest_forum import service
from nest_forum.service import ForumError

router = APIRouter()
moderator = require_role("moderator")


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "forum")


def _readable(request: Request) -> None:
    if not _state(request)["public_read"] and current_user(request) is None:
        raise HTTPException(404)


def access(ask: Any, user: CurrentUser | None, b: Any, public_read: bool) -> tuple[bool, bool]:
    """(may read, may post) on this board. A public board: anyone reads (unless public_read
    is off), members post. A board with a scope: those the application lets in (its answer
    to forum.access, {"read": .., "post": ..}, asked through ``ask``); no one else.
    Moderators: everywhere."""
    if user is not None and user.has("moderator"):
        return True, True
    if b.scope is None:
        return (public_read or user is not None), user is not None
    if user is None:
        return False, False
    said = ask({"user": user.id, "scope": b.scope}) or {}
    return bool(said.get("read")), bool(said.get("read") and said.get("post"))


def _may(request: Request, b: Any) -> tuple[bool, bool]:
    """(may read, may post); a board put away (or in one) is read only, for everyone."""
    nest = request.app.state.nest
    read, write = access(
        lambda key: nest.lookup("forum.access", key),
        current_user(request),
        b,
        _state(request)["public_read"],
    )
    if write and service.archived_in(nest.bindings.get("nest.db"), b):
        write = False
    return read, write


def _admin(request: Request) -> str | None:
    """The forum's admin pages, if the application has an admin panel."""
    return admin_url(request, "forum") if request.app.state.nest.admin_root else None


def _board_or_404(request: Request, b: Any, *, post: bool = False) -> Any:
    """The board, if this visitor may read it (and post, if asked): a board one may not
    read is not found, so a private one does not say it is there."""
    if b is None:
        raise HTTPException(404)
    read, write = _may(request, b)
    if not read or (post and not write):
        raise HTTPException(404)
    return b


def names_for(request: Request, db: Any, b: Any, ids: list[int]) -> dict[int, Any]:
    """The names posts show: on a public board, the accounts' own when public_names is
    account (never their emails); else as the application knows its people."""
    nest = request.app.state.nest
    if (b is None or b.scope is None) and _state(request).get("public_names") == "account":
        return {
            uid: replace(u, name=u.name or f"#{uid}", email="")
            for uid, u in users_by_ids(db, ids).items()
        }
    return known_as(nest, db, ids)


def topic_url(base: str, t: Any) -> str:
    return f"{base}/t/{t.id}/{quote(t.slug)}"


def _page(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        return 1


@router.get("/")
def index(request: Request, db: Database = bound(Database)):
    _readable(request)
    rows = service.boards(db)
    names = names_for(
        request, db, None, [r.last.last_author_id for r in rows if r.last and r.last.last_author_id]
    )
    return render(request, "forum/index.html", rows=rows, names=names, base=_state(request)["base"])


@router.get("/{slug}/")
def board_page(request: Request, slug: str, db: Database = bound(Database)):
    b = _board_or_404(request, service.board(db, slug))
    page, per_page = _page(request), _state(request)["topics_per_page"]
    user = current_user(request)
    moderating = bool(user and user.has("moderator"))
    put_away = request.query_params.get("archived") == "1"
    rows, total = service.topics(
        db, b.id, page=page, per_page=per_page, include_hidden=moderating, archived=put_away
    )
    _rows, archived_topics = service.topics(
        db, b.id, page=1, per_page=1, include_hidden=moderating, archived=True
    )
    names = names_for(
        request,
        db,
        b,
        [t.author_id for t in rows] + [t.last_author_id for t in rows if t.last_author_id],
    )
    children = service.boards(db, parent_id=b.id)
    names |= names_for(
        request,
        db,
        b,
        [r.last.last_author_id for r in children if r.last and r.last.last_author_id],
    )
    return render(
        request,
        "forum/board.html",
        boards=children,
        trail=service.trail(db, b),
        fragment="topics",
        board=b,
        topics=rows,
        names=names,
        may_post=_may(request, b)[1],
        archived=service.archived_in(db, b),
        put_away=put_away,
        archived_topics=archived_topics,
        admin=_admin(request),
        page=page,
        pages=max(1, math.ceil(total / per_page)),
        base=_state(request)["base"],
    )


@router.post("/{slug}/boards")
async def add_board(
    request: Request,
    slug: str,
    user: CurrentUser = Depends(moderator),
    db: Database = bound(Database),
):
    """A board in this board (moderators): its scope, so its members, are this one's."""
    parent = await run_in_threadpool(service.board, db, slug)
    if parent is None:
        raise HTTPException(404)
    if await run_in_threadpool(service.archived_in, db, parent):
        raise HTTPException(400, translator(request)("This board is closed."))
    form = await request.form()
    title = str(form.get("title", "")).strip()[:200]
    if not title:
        raise HTTPException(400, translator(request)("A board needs a title."))
    await run_in_threadpool(
        lambda: service.ensure_board(
            db,
            title,
            slug=f"{parent.slug}-{title}",
            description=str(form.get("description", "")).strip()[:2000],
            parent=parent,
        )
    )
    return RedirectResponse(f"{_state(request)['base']}/{parent.slug}/", status_code=303)


@router.get("/{slug}/new")
def new_topic(
    request: Request,
    slug: str,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    b = _board_or_404(request, service.board(db, slug), post=True)
    return render(
        request, "forum/new.html", board=b, values={}, error=None, base=_state(request)["base"]
    )


@router.post("/{slug}/new")
async def create_topic(
    request: Request,
    slug: str,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    b = await run_in_threadpool(service.board, db, slug)
    b = await run_in_threadpool(lambda: _board_or_404(request, b, post=True))
    form = await request.form()
    values = {"title": str(form.get("title", "")), "body": str(form.get("body", ""))}
    state = _state(request)
    try:
        if await run_in_threadpool(service.recent_posts, db, user.id) >= state["posts_per_minute"]:
            raise ForumError("Slow down a little; try again in a minute.")
        t, _p = await run_in_threadpool(
            service.start_topic, db, b, user.id, values["title"], values["body"]
        )
    except ForumError as e:
        return render(
            request,
            "forum/new.html",
            board=b,
            values=values,
            base=state["base"],
            error=translator(request)(e.message, **e.params),
            status_code=400,
        )
    return RedirectResponse(topic_url(state["base"], t), status_code=303)


@router.get("/t/{topic_id:int}")
@router.get("/t/{topic_id:int}/{slug}")
def topic_page(request: Request, topic_id: int, slug: str = "", db: Database = bound(Database)):
    state = _state(request)
    user = current_user(request)
    moderating = bool(user and user.has("moderator"))
    t = service.topic(db, topic_id)
    if t is None or (t.hidden and not moderating):
        raise HTTPException(404)
    b = _board_or_404(request, service.board_by_id(db, t.board_id))
    if slug != t.slug:
        return RedirectResponse(topic_url(state["base"], t), status_code=301)
    per_page = state["posts_per_page"]
    rows, total = service.posts(db, t.id, page=1, per_page=1, include_hidden=moderating)
    pages = max(1, math.ceil(total / per_page))
    page = (
        min(_page(request), pages)
        if "page" in request.query_params
        else pages
        if request.query_params.get("last")
        else _page(request)
    )
    rows, _ = service.posts(db, t.id, page=page, per_page=per_page, include_hidden=moderating)
    service.count_view(db, t.id)
    names = names_for(request, db, b, [p.author_id for p in rows])
    return render(
        request,
        "forum/topic.html",
        topic=t,
        board=b,
        posts=rows,
        names=names,
        page=page,
        pages=pages,
        base=state["base"],
        live=page == pages,
        edit_minutes=state["edit_minutes"],
        may_edit=lambda p: service.may_edit(p, user, state["edit_minutes"]),
        moderating=moderating,
        may_post=_may(request, b)[1] and not t.archived,
        admin=_admin(request),
        trail=service.trail(db, b),
        error=None,
        body="",
    )


def post_html(request: Request, p: Any, *, controls: bool, board: Any = None) -> str:
    nest = request.app.state.nest
    names = names_for(request, nest.bindings.get("nest.db"), board, [p.author_id])
    user = current_user(request) if controls else None
    state = _state(request)
    return nest.render_block(
        "forum/topic.html",
        "post",
        p=p,
        names=names,
        base=state["base"],
        csrf_field="",
        may_edit=lambda x: service.may_edit(x, user, state["edit_minutes"]) if controls else False,
        moderating=False,
    )


@router.post("/t/{topic_id:int}/reply")
async def reply(
    request: Request,
    topic_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    state = _state(request)
    form = await request.form()
    body = str(form.get("body", ""))
    t = await run_in_threadpool(service.topic, db, topic_id)
    if t is None:
        raise HTTPException(404)
    b = await run_in_threadpool(service.board_by_id, db, t.board_id)
    b = await run_in_threadpool(lambda: _board_or_404(request, b, post=True))
    try:
        if await run_in_threadpool(service.recent_posts, db, user.id) >= state["posts_per_minute"]:
            raise ForumError("Slow down a little; try again in a minute.")
        p = await run_in_threadpool(service.reply, db, topic_id, user.id, body)
    except ForumError as e:
        message = translator(request)(e.message, **e.params)
        if is_htmx(request):
            return render(
                request,
                "forum/topic.html",
                fragment="reply",
                topic=t,
                error=message,
                body=body,
                base=state["base"],
            )
        raise HTTPException(400, message) from None
    # Everyone reading the topic, the poster included, gets the post over SSE.
    html = await run_in_threadpool(lambda: post_html(request, p, controls=False, board=b))
    state["realtime"].publish(f"forum.topic.{topic_id}", "post", html)
    if is_htmx(request):
        return render(
            request,
            "forum/topic.html",
            fragment="reply",
            topic=t,
            error=None,
            body="",
            base=state["base"],
        )
    return RedirectResponse(f"{topic_url(state['base'], t)}?last=1#post-{p.id}", status_code=303)


@router.get("/p/{post_id:int}/edit")
def edit_form(
    request: Request,
    post_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    p = service.post(db, post_id)
    state = _state(request)
    if p is None or not service.may_edit(p, user, state["edit_minutes"]):
        raise HTTPException(404)
    t = service.topic(db, p.topic_id)
    if t is None or t.archived:
        raise HTTPException(404)
    _board_or_404(request, service.board_by_id(db, t.board_id), post=True)
    return render(request, "forum/edit.html", fragment="edit", p=p, base=state["base"])


@router.post("/p/{post_id:int}/edit")
async def save_edit(
    request: Request,
    post_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    state = _state(request)
    p = await run_in_threadpool(service.post, db, post_id)
    if p is None or not service.may_edit(p, user, state["edit_minutes"]):
        raise HTTPException(404)

    def board_of() -> Any:
        t = service.topic(db, p.topic_id)
        return _board_or_404(request, service.board_by_id(db, t.board_id) if t else None, post=True)

    b = await run_in_threadpool(board_of)
    form = await request.form()
    try:
        p = await run_in_threadpool(service.edit, db, post_id, str(form.get("body", "")))
    except ForumError as e:
        raise HTTPException(400, translator(request)(e.message, **e.params)) from None
    if is_htmx(request):
        return Response(
            await run_in_threadpool(lambda: post_html(request, p, controls=True, board=b)),
            media_type="text/html",
        )
    t = await run_in_threadpool(service.topic, db, p.topic_id)
    return RedirectResponse(topic_url(state["base"], t), status_code=303)


@router.post("/t/{topic_id:int}/moderate")
async def moderate(
    request: Request,
    topic_id: int,
    user: CurrentUser = Depends(moderator),
    db: Database = bound(Database),
):
    form = await request.form()
    try:
        t = await run_in_threadpool(
            service.moderate_topic, db, topic_id, str(form.get("action", ""))
        )
    except ForumError as e:
        raise HTTPException(400, e.message) from None
    if t is None:
        raise HTTPException(404)
    return RedirectResponse(topic_url(_state(request)["base"], t), status_code=303)


@router.post("/p/{post_id:int}/hide")
async def hide(
    request: Request,
    post_id: int,
    user: CurrentUser = Depends(moderator),
    db: Database = bound(Database),
):
    form = await request.form()
    p = await run_in_threadpool(service.hide_post, db, post_id, str(form.get("hidden", "1")) == "1")
    if p is None:
        raise HTTPException(404)
    t = await run_in_threadpool(service.topic, db, p.topic_id)
    return RedirectResponse(topic_url(_state(request)["base"], t), status_code=303)
