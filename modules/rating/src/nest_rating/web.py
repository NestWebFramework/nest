"""The rating widget any page embeds, the vote it sends, and the admin panel's page."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import Markup
from nest_db import Database

from nest import bound, is_htmx, render, translator
from nest.host import module_state
from nest_rating import service

router = APIRouter()
admin = APIRouter()
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()
YEAR = 365 * 86400


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "rating")


def _user_id(request: Request) -> int | None:
    user = getattr(request.state, "user", None)
    uid = getattr(user, "id", None)
    return int(uid) if uid else None


def _voter(request: Request) -> str:
    uid = _user_id(request)
    if uid:
        return f"u:{uid}"
    return request.cookies.get(service.COOKIE, "")


def widget(
    request: Request, subject: str, kind: str = "stars", name: str = "", item: str = ""
) -> Markup:
    """A subject's rating and its buttons, as a page embeds it:
    {{ rating("coaches.operator:flixbus", "stars", name="FlixBus", item="Organization") }}
    (``item``: the schema.org type the page is about, for the stars in search engines)."""
    if kind not in service.KINDS or not service.SUBJECT.match(subject):
        return Markup("")
    nest = request.app.state.nest
    st = _state(request)
    db = nest.bindings.get("nest.db")
    summed = service.summary(db, subject, kind)
    context = {
        **nest.template_context(request),
        "subject": subject,
        "kind": kind,
        "name": name,
        "sig": service.sign(nest.secret, subject, kind),
        "s": summed,
        "mine": service.mine(db, subject, _voter(request)),
        "enough": summed.count >= int(st["host"].settings.get("min_votes") or 5),
        "action": (st["base"] or "") + "/vot",
        "ld": _ld(st, summed, name, item),
    }
    return Markup(nest.templates.get_template("rating/widget.html").render(context))


def _ld(st: dict, s: service.Summed, name: str, item: str) -> str:
    """schema.org AggregateRating for the stars, when the page names what it is about and
    there are enough votes (search engines show stars only for some kinds of things)."""
    host = st["host"]
    if (
        s.kind != "stars"
        or not item
        or not name
        or not host.settings.get("schema")
        or s.count < int(host.settings.get("min_votes") or 5)
    ):
        return ""
    data = {
        "@context": "https://schema.org",
        "@type": item,
        "name": name,
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": s.average,
            "ratingCount": s.count,
            "bestRating": 5,
            "worstRating": 1,
        },
    }
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _too_many(request: Request, most: int) -> bool:
    who = request.client.host if request.client else "-"
    now = time.time()
    with _hits_lock:
        hits = [t for t in _hits.get(who, []) if now - t < 60]
        hits.append(now)
        _hits[who] = hits
        if len(_hits) > 5000:
            _hits.clear()
    return len(hits) > most


@router.post("/vot")
async def vote(request: Request, db: Database = bound(Database)):
    nest = request.app.state.nest
    st = _state(request)
    form = await request.form()
    subject, kind = str(form.get("subject", "")), str(form.get("kind", ""))
    if str(form.get("sig", "")) != service.sign(nest.secret, subject, kind):
        raise HTTPException(400)
    try:
        value = int(str(form.get("value", "")))
    except ValueError:
        raise HTTPException(400) from None
    t = translator(request)
    voter = _voter(request)
    fresh = not voter
    if fresh:
        voter = service.new_voter()
    note = ""
    if _too_many(request, int(st["host"].settings.get("per_minute") or 10)):
        note = t("Too many votes in a minute from here: try again in a minute.")
    else:
        agent = request.headers.get("user-agent", "")
        address = request.client.host if request.client else ""
        result = service.vote(
            db, subject, kind, value, voter, service.fingerprint(nest.secret, address, agent)
        )
        if result == "bad":
            raise HTTPException(400)
        if result == "closed":
            note = t("Voting is closed here.")
        elif result == "removed":
            note = t("Your vote was taken back.")
        else:
            note = t("Thank you for your vote.")
    if is_htmx(request):
        html = str(widget(request_with(request, voter), subject, kind, str(form.get("name", ""))))
        html = html.replace("<!--note-->", f'<p class="nest-rating-note" role="status">{note}</p>')
        response: Any = HTMLResponse(html, headers={"cache-control": "no-store"})
    else:
        back = str(form.get("back", "/"))
        if not back.startswith("/") or back.startswith("//"):
            back = "/"
        response = RedirectResponse(back, status_code=303)
    if fresh and not _user_id(request):
        response.set_cookie(
            service.COOKIE,
            voter,
            max_age=YEAR,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


def request_with(request: Request, voter: str) -> Request:
    """The request as if its voter cookie were already set (for the widget drawn in the
    answer that sets it)."""
    if request.cookies.get(service.COOKIE) == voter or voter.startswith("u:"):
        return request
    request._cookies = {**request.cookies, service.COOKIE: voter}  # noqa: SLF001
    return request


# --- the admin panel --------------------------------------------------------------------


@admin.get("/")
def overview(request: Request, db: Database = bound(Database)):
    return render(
        request,
        "rating/admin.html",
        rows=service.overview(db),
        bursts=service.bursts(db),
        base=request.url.path.rstrip("/"),
    )


@admin.post("/inchide")
async def close(request: Request, db: Database = bound(Database)):
    form = await request.form()
    subject = str(form.get("subject", ""))
    service.close(db, subject, str(form.get("closed", "")) == "1")
    return RedirectResponse("./", status_code=303)


@admin.post("/sterge")
async def reset(request: Request, db: Database = bound(Database)):
    form = await request.form()
    service.reset(db, str(form.get("subject", "")))
    return RedirectResponse("./", status_code=303)


@admin.post("/uita")
async def forget(request: Request, db: Database = bound(Database)):
    form = await request.form()
    service.forget_print(db, str(form.get("print", "")))
    return RedirectResponse("./", status_code=303)
