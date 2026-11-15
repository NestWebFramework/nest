"""The forum over HTTP; new replies reach every open copy of the topic over SSE."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, current_user, known_as, require_role, require_user
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import bound, is_htmx, render, translator
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
    names = known_as(
        request.app.state.nest,
        db,
        [r.last.last_author_id for r in rows if r.last and r.last.last_author_id],
    )
    return render(request, "forum/index.html", rows=rows, names=names, base=_state(request)["base"])


@router.get("/{slug}/")
def board_page(request: Request, slug: str, db: Database = bound(Database)):
    _readable(request)
    b = service.board(db, slug)
    if b is None:
        raise HTTPException(404)
    page, per_page = _page(request), _state(request)["topics_per_page"]
    user = current_user(request)
    rows, total = service.topics(
        db, b.id, page=page, per_page=per_page, include_hidden=bool(user and user.has("moderator"))
    )
    names = known_as(
        request.app.state.nest,
        db,
        [t.author_id for t in rows] + [t.last_author_id for t in rows if t.last_author_id],
    )
    return render(
        request,
        "forum/board.html",
        fragment="topics",
        board=b,
        topics=rows,
        names=names,
        page=page,
        pages=max(1, math.ceil(total / per_page)),
        base=_state(request)["base"],
    )


@router.get("/{slug}/new")
def new_topic(
    request: Request,
    slug: str,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    b = service.board(db, slug)
    if b is None:
        raise HTTPException(404)
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
    if b is None:
        raise HTTPException(404)
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
    _readable(request)
    state = _state(request)
    user = current_user(request)
    moderating = bool(user and user.has("moderator"))
    t = service.topic(db, topic_id)
    if t is None or (t.hidden and not moderating):
        raise HTTPException(404)
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
    b = service.board_by_id(db, t.board_id)
    names = known_as(request.app.state.nest, db, [p.author_id for p in rows])
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
        error=None,
        body="",
    )


def post_html(request: Request, p: Any, *, controls: bool) -> str:
    nest = request.app.state.nest
    names = known_as(nest, nest.bindings.get("nest.db"), [p.author_id])
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
    html = await run_in_threadpool(post_html, request, p, controls=False)
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
    form = await request.form()
    try:
        p = await run_in_threadpool(service.edit, db, post_id, str(form.get("body", "")))
    except ForumError as e:
        raise HTTPException(400, translator(request)(e.message, **e.params)) from None
    if is_htmx(request):
        return Response(
            await run_in_threadpool(post_html, request, p, controls=True), media_type="text/html"
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
