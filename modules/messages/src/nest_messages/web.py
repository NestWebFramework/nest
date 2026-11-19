"""Conversations over HTTP; new messages reach their participants over SSE."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, find_person, known_as, require_user
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import bound, is_htmx, render, translator
from nest.host import module_state
from nest_messages import service
from nest_messages.service import MessageError

router = APIRouter()


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "messages")


@router.get("/")
def inbox(
    request: Request,
    archived: int = 0,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    rows = service.inbox(db, user.id, archived=bool(archived))
    names = known_as(
        request.app.state.nest,
        db,
        [uid for r in rows for uid in r.others] + [r.last.sender_id for r in rows if r.last],
    )
    return render(
        request,
        "messages/inbox.html",
        fragment="rows",
        rows=rows,
        names=names,
        me=user,
        archived=bool(archived),
        base=_state(request)["base"],
    )


@router.get("/new")
def new(request: Request, to: str = "", user: CurrentUser = Depends(require_user)):
    return render(
        request, "messages/new.html", values={"to": to}, error=None, base=_state(request)["base"]
    )


@router.post("/new")
async def create(
    request: Request, user: CurrentUser = Depends(require_user), db: Database = bound(Database)
):
    state = _state(request)
    t = translator(request)
    form = await request.form()
    values = {k: str(form.get(k, "")) for k in ("to", "subject", "body")}

    def again(error: str) -> Response:
        return render(
            request,
            "messages/new.html",
            values=values,
            error=error,
            base=state["base"],
            status_code=400,
        )

    names = [n.strip() for n in values["to"].replace(";", ",").split(",") if n.strip()]
    if not names:
        return again(t("Say whom you are writing to."))
    if len(names) > state["max_recipients"]:
        return again(t("At most {n} people in one conversation.", n=state["max_recipients"]))
    found = []
    for name in names:
        member = await run_in_threadpool(find_person, request.app.state.nest, db, name)
        if member is None:
            return again(t("Nobody here is called “{name}”.", name=name))
        found.append(member.id)
    if await run_in_threadpool(service.sent_recently, db, user.id) >= state["per_hour"]:
        return again(t("You have sent many messages this hour; try again later."))
    try:
        c, m = await run_in_threadpool(
            service.start, db, user.id, found, values["subject"], values["body"]
        )
    except MessageError as e:
        return again(t(e.message, **e.params))
    await run_in_threadpool(deliver, request, c.id, m)
    return RedirectResponse(f"{state['base']}/{c.id}", status_code=303)


@router.get("/{conversation_id:int}")
def conversation(
    request: Request,
    conversation_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    c = service.conversation(db, conversation_id, user.id)
    if c is None:
        raise HTTPException(404)
    rows = service.messages(db, c.id)
    people = service.participants(db, c.id)
    service.mark_read(db, c.id, user.id)
    return render(
        request,
        "messages/conversation.html",
        conversation=c,
        messages=rows,
        names=known_as(request.app.state.nest, db, people),
        people=people,
        me=user,
        me_id=user.id,
        base=_state(request)["base"],
        error=None,
        body="",
    )


def message_html(request: Request, m: Any, viewer_id: int) -> str:
    nest = request.app.state.nest
    names = known_as(nest, nest.bindings.get("nest.db"), [m.sender_id])
    return nest.render_block(
        "messages/conversation.html", "message", m=m, names=names, me_id=viewer_id
    )


def deliver(request: Request, conversation_id: int, m: Any) -> None:
    """Push a new message to each participant's own channel, rendered for them."""
    db = request.app.state.nest.bindings.get("nest.db")
    realtime = _state(request)["realtime"]
    for uid in service.participants(db, conversation_id):
        channel = f"messages.user.{uid}"
        if not realtime.listening(channel):
            continue
        realtime.publish(channel, f"conversation-{conversation_id}", message_html(request, m, uid))
        realtime.publish(channel, "inbox", str(service.unread_count(db, uid)))


@router.post("/{conversation_id:int}/reply")
async def reply(
    request: Request,
    conversation_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    state = _state(request)
    form = await request.form()
    body = str(form.get("body", ""))
    c = await run_in_threadpool(service.conversation, db, conversation_id, user.id)
    if c is None:
        raise HTTPException(404)
    error = None
    try:
        if await run_in_threadpool(service.sent_recently, db, user.id) >= state["per_hour"]:
            raise MessageError("You have sent many messages this hour; try again later.")
        m = await run_in_threadpool(service.reply, db, conversation_id, user.id, body)
        await run_in_threadpool(deliver, request, conversation_id, m)
        body = ""
    except MessageError as e:
        error = translator(request)(e.message, **e.params)
    if is_htmx(request):
        return render(
            request,
            "messages/conversation.html",
            fragment="reply",
            conversation=c,
            base=state["base"],
            error=error,
            body=body,
        )
    if error:
        raise HTTPException(400, error)
    return RedirectResponse(f"{state['base']}/{conversation_id}", status_code=303)


@router.post("/{conversation_id:int}/archive")
def archive(
    request: Request,
    conversation_id: int,
    user: CurrentUser = Depends(require_user),
    db: Database = bound(Database),
):
    service.archive(db, conversation_id, user.id)
    return RedirectResponse(f"{_state(request)['base']}/", status_code=303)
