"""Cookies and consent, for every module of a site.

Modules declare their cookies (the answer "consent.cookies"); this module asks the visitor,
once, for the purposes that need consent, keeps the answer in the cookie ``nest_consent``,
and tells every module the same: in a template ``consent().allowed("statistics")``, in
Python ``nest_consent.allowed(request, "statistics")``, in a page's script
``window.nestConsent.allowed("statistics")``. Its page (where it is mounted) lists every
cookie of the site, by purpose, and lets the visitor change their choice.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from nest import ModuleHost, render
from nest.host import module_state
from nest_consent.cookies import ASKED, COOKIE, Choice, State, declared, fingerprint

__all__ = ["allowed", "state"]

router = APIRouter()
CACHE_SECONDS = (
    30  # the declarations are asked again this often (a setting changed in the admin panel)
)


def _declared(host: ModuleHost) -> tuple[list, str]:
    st = host.state
    at, cookies, fp = st.get("declared", (0.0, [], ""))
    if time.time() - at > CACHE_SECONDS:
        cookies = declared(host)
        fp = fingerprint(cookies)
        st["declared"] = (time.time(), cookies, fp)
    return cookies, fp


def state(request: Request) -> State:
    """The cookies, the visitor's choice and whether to ask, for this request."""
    host = module_state(request, "consent")["host"]
    cookies, fp = _declared(host)
    return State(cookies, Choice.decode(request.cookies.get(COOKIE)), fp)


def allowed(request: Request, purpose: str, service: str = "") -> bool:
    """Whether the visitor allowed ``purpose`` (necessary: always), and that ``service`` of it."""
    return state(request).allowed(purpose, service)


def setup(host: ModuleHost) -> None:
    host.state.update(host=host, base="" if host.route in (None, "/") else host.route)

    # other modules ask whether the visitor allowed a purpose (the planner, before it saves a
    # trip in a cookie): {"request": ..., "purpose": "preferences", "service": "..."}
    host.answer(
        "consent.allowed",
        lambda q: (
            allowed(q["request"], q["purpose"], q.get("service", ""))
            if isinstance(q, dict)
            else None
        ),
    )

    @host.context
    def _consent(request: Any) -> dict[str, Any]:
        return {
            "consent": lambda: state(request),
            "consent_url": host.state["base"] or "/",
            "consent_notice": lambda: str(host.settings.get("notice") or ""),
        }

    host.mount(router)


def _back(request: Request, value: str) -> str:
    """Where to go after choosing: a path of this site, never elsewhere."""
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return module_state(request, "consent")["base"] or "/"


@router.get("/")
def page(request: Request):
    st = module_state(request, "consent")
    return render(
        request,
        "consent/page.html",
        state=state(request),
        policy=str(st["host"].settings.get("policy") or ""),
        base=st["base"],
    )


@router.post("/alege")
async def choose(request: Request):
    """The visitor's choice: everything, only what is necessary, or the purposes ticked."""
    form = await request.form()
    current = state(request)
    action = str(form.get("action") or "")
    if action == "all":
        ok = set(current.needed)
    elif action == "necessary":
        ok = set()
    else:
        ok = {p for p in form.getlist("purpose") if p in ASKED}
    # a purpose with several services: those left unticked are refused (only when the form showed them)
    shown = {x for x in form.getlist("service_shown")}
    ticked = {x for x in form.getlist("service")}
    refused = shown - ticked if action == "choose" else set()
    if (
        action == "choose"
    ):  # a purpose allowed only through its services: allowed when one of them is
        for purpose in ASKED:
            keys = {k for k, _ in current.services(purpose)}
            if keys and keys <= shown and keys & ticked:
                ok.add(purpose)
    days = int(module_state(request, "consent")["host"].settings.get("days") or 180)
    response = RedirectResponse(_back(request, str(form.get("back") or "")), status_code=303)
    response.set_cookie(
        COOKIE,
        Choice(current.current, ok, refused).encode(),
        max_age=days * 86400,
        samesite="lax",
        secure=request.app.state.nest.production,
        httponly=False,  # the pages' scripts read it too (window.nestConsent)
        path="/",
    )
    return response
