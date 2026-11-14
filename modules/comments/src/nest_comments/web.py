"""Comment threads in any page, posting, and moderation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from markupsafe import Markup
from nest_auth import CurrentUser, current_user, require_role
from nest_db import Database
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, is_htmx, local_path, render, translator
from nest.host import module_state
from nest_comments import service
from nest_comments.models import Comment, utcnow
from nest_comments.service import CommentError

router = APIRouter()
admin = APIRouter()  # moderation: the admin panel mounts it at <admin route>/comments
moderator = require_role("moderator")


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "comments")


def thread_html(
    request: Request, subject: str, *, notice: str = "", error: str = "", values: dict | None = None
) -> Markup:
    """A subject's thread and its form, as any page embeds it with {{ comments(subject) }}."""
    nest = request.app.state.nest
    state = _state(request)
    db = nest.bindings.get("nest.db")
    roots, total = service.thread(db, subject)
    user = current_user(request)
    context = {
        **nest.template_context(request),
        "subject": subject,
        "sig": service.sign(nest.secret, subject),
        "stamp": service.stamp(nest.secret),
        "roots": roots,
        "total": total,
        "user": user,
        "action": state["action"],
        "can_post": user is not None or state["allow_guests"],
        "login": state["login"],
        "notice": notice,
        "error": error,
        "values": values or {},
        "max_depth": state["max_depth"],
    }
    return Markup(nest.templates.get_template("comments/thread.html").render(context))


def _status_for(state: dict[str, Any], user: CurrentUser | None) -> str:
    mode = state["moderation"]
    if user is not None and user.has("moderator"):
        return "approved"
    if mode == "all" or (mode == "guests" and user is None):
        return "pending"
    return "approved"


@router.post("/post")
async def post(request: Request, db: Database = bound(Database)):
    nest = request.app.state.nest
    state = _state(request)
    t = translator(request)
    form = await request.form()
    subject = str(form.get("subject", ""))
    referer = urlsplit(request.headers.get("referer", ""))
    same_site = referer.netloc in ("", request.headers.get("host", ""))
    back = (
        local_path(referer.path + (f"?{referer.query}" if referer.query else ""))
        if same_site
        else "/"
    )
    if not service.SUBJECT.match(subject) or str(form.get("sig", "")) != service.sign(
        nest.secret, subject
    ):
        raise HTTPException(400, "comments are not open here")
    user = current_user(request)
    values = {k: str(form.get(k, "")) for k in ("author_name", "author_email", "body", "parent_id")}

    def again(error: str = "", notice: str = "", keep: bool = True) -> Response:
        if not is_htmx(request):
            return RedirectResponse(back, status_code=303)
        html = thread_html(
            request, subject, error=error, notice=notice, values=values if keep else None
        )
        return Response(str(html), media_type="text/html")

    if user is None and not state["allow_guests"]:
        return again(t("Sign in to comment."))
    if str(form.get("website", "")):  # the honeypot: people cannot see it, robots fill it
        return again(notice=t("Thank you. Your comment awaits approval."), keep=False)
    age = service.stamp_age(nest.secret, str(form.get("stamp", "")))
    if age is None or age < state["min_seconds"] or age > 86400:
        return again(t("That was quick. Please send it again."))
    address = service.address_hash(nest.secret, request.client.host if request.client else "")

    def recent() -> int:
        with db.session() as s:
            return (
                s.scalar(
                    select(func.count())
                    .select_from(Comment)
                    .where(
                        Comment.address == address,
                        Comment.created_at > utcnow() - timedelta(hours=1),
                    )
                )
                or 0
            )

    # Members are accountable for what they write; the limit is for guests.
    if user is None and await run_in_threadpool(recent) >= state["per_hour"]:
        return again(t("Too many comments from here; try again later."))
    parent = values["parent_id"]
    status = _status_for(state, user)
    try:
        await run_in_threadpool(
            service.add,
            db,
            subject,
            values["body"],
            author_name=(user.label if user else values["author_name"]),
            author_email=(user.email if user else values["author_email"]),
            user_id=user.id if user else None,
            parent_id=int(parent) if parent.isdigit() else None,
            status=status,
            address=address,
            max_depth=state["max_depth"],
        )
    except CommentError as e:
        return again(t(e.message, **e.params))
    notice = (
        t("Thank you. Your comment awaits approval.")
        if status == "pending"
        else t("Your comment is published.")
    )
    return again(notice=notice, keep=False)


@admin.get("/")
def moderate(
    request: Request,
    status: str = "pending",
    user: CurrentUser = Depends(moderator),
    db: Database = bound(Database),
):
    status = status if status in ("pending", "spam", "approved") else "pending"
    return render(
        request,
        "comments/moderate.html",
        comments=service.queue(db, status),
        status=status,
        action=admin_url(request, "comments"),
    )


@admin.post("/{comment_id:int}/status")
async def change(
    request: Request,
    comment_id: int,
    user: CurrentUser = Depends(moderator),
    db: Database = bound(Database),
):
    form = await request.form()
    try:
        c = await run_in_threadpool(service.set_status, db, comment_id, str(form.get("status", "")))
    except CommentError as e:
        raise HTTPException(400, e.message) from None
    if c is None:
        raise HTTPException(404)
    if is_htmx(request):
        return render(
            request,
            "comments/moderate.html",
            fragment="row",
            c=c,
            action=admin_url(request, "comments"),
            status=c.status,
        )
    return RedirectResponse(admin_url(request, "comments") + "/", status_code=303)
