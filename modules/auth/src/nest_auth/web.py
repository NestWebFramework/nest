"""Sign-in over HTTP: the middleware, the dependencies other modules use, the pages."""

from __future__ import annotations

import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_db import Database
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from nest import bound, is_htmx, render
from nest.host import module_state
from nest_auth import sessions
from nest_auth.sessions import AccountError, CurrentUser

COOKIE = "nest_session"
SKIP_PREFIXES = ("/assets/", "/healthz", "/_nest/")


# --- throttling --------------------------------------------------------------------


class Throttle:
    """Failed sign-ins per (email, address) in a sliding window. One process's memory."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._failures.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._recent(key, now).append(now)
            if len(self._failures) > 10_000:  # forget the oldest keys rather than grow forever
                for old in list(self._failures)[:1000]:
                    del self._failures[old]

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# --- who is asking -----------------------------------------------------------------


class AuthMiddleware:
    """Resolves the session cookie once per request into ``request.state.user``."""

    def __init__(self, app: ASGIApp, *, session_days: int):
        self.app = app
        self.days = session_days

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            user = None
            if not scope["path"].startswith(SKIP_PREFIXES):
                token = _cookie(scope, COOKIE)
                if token:
                    db = scope["app"].state.nest.bindings.get("nest.db")
                    user = await run_in_threadpool(sessions.user_for, db, token, days=self.days)
            scope.setdefault("state", {})["user"] = user
        await self.app(scope, receive, send)


def _cookie(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:  # noqa: BLE001 - a malformed cookie is no cookie
                continue
            if name in jar:
                return jar[name].value
    return None


def current_user(request: Request) -> CurrentUser | None:
    """A dependency: who is signed in, or None."""
    return getattr(request.state, "user", None)


def _sign_in_redirect(request: Request) -> HTTPException:
    login = module_state(request, "auth").get("login_url", "/login")
    target = f"{login}?next={quote(request.url.path + ('?' + request.url.query if request.url.query else ''))}"
    if is_htmx(request):
        return HTTPException(401, "sign in", headers={"HX-Redirect": target})
    if request.method == "GET":
        return HTTPException(303, "sign in", headers={"Location": target})
    return HTTPException(401, "sign in required")


def require_user(request: Request) -> CurrentUser:
    """A dependency: the signed-in user; anyone else is sent to sign in."""
    user = current_user(request)
    if user is None:
        raise _sign_in_redirect(request)
    return user


def require_role(*roles: str) -> Any:
    """A dependency: a signed-in user with one of ``roles`` (admin has every role)."""

    def check(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if not user.has(*roles):
            raise HTTPException(403, "not allowed")
        return user

    return check


# --- the pages ---------------------------------------------------------------------


def safe_next(value: str | None) -> str:
    """Only a path on this site: an open redirect is how a phishing link borrows trust."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(ch) < 32 for ch in value) or urlsplit(value).netloc:
        return "/"
    return value


router = APIRouter()


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "auth")


def _signed_in(request: Request, token: str, target: str) -> Response:
    state = _state(request)
    response: Response
    if is_htmx(request):
        response = Response(status_code=200, headers={"HX-Redirect": target})
    else:
        response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        COOKIE,
        token,
        max_age=state["session_days"] * 86400,
        httponly=True,
        samesite="lax",
        secure=request.app.state.nest.production,
        path="/",
    )
    return response


def _form_page(request: Request, template: str, status: int, **values: Any) -> Response:
    # htmx swaps only 2xx answers, so a refused form is answered 200 to htmx.
    return render(
        request,
        template,
        fragment="form",
        status_code=200 if is_htmx(request) else status,
        **values,
    )


def _can_register(request: Request, db: Any) -> bool:
    return bool(_state(request)["allow_registration"]) or sessions.count_users(db) == 0


@router.get("/login")
def login_page(request: Request, next: str = "/", db: Database = bound(Database)):
    return render(
        request,
        "auth/login.html",
        next=safe_next(next),
        email="",
        error=None,
        can_register=_can_register(request, db),
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: Database = bound(Database),
):
    state = _state(request)
    target = safe_next(next)
    client = request.client.host if request.client else "-"
    key = f"{sessions.normalize_email(email)}|{client}"
    values = {"next": target, "email": email, "can_register": _can_register(request, db)}
    if state["throttle"].blocked(key):
        minutes = state["throttle"].window // 60
        return _form_page(
            request,
            "auth/login.html",
            429,
            error=f"Too many attempts. Try again in {minutes} minutes.",
            **values,
        )
    user = sessions.authenticate(db, email, password)
    if user is None:
        state["throttle"].fail(key)
        return _form_page(
            request, "auth/login.html", 401, error="Wrong email or password.", **values
        )
    state["throttle"].clear(key)
    token = sessions.open_session(
        db, user, days=state["session_days"], user_agent=request.headers.get("user-agent", "")
    )
    return _signed_in(request, token, target)


@router.post("/logout")
def logout(request: Request, db: Database = bound(Database)):
    token = request.cookies.get(COOKIE)
    if token:
        sessions.close_session(db, token)
    response: Response
    if is_htmx(request):
        response = Response(status_code=200, headers={"HX-Redirect": "/"})
    else:
        response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/register")
def register_page(request: Request, db: Database = bound(Database)):
    if not _can_register(request, db):
        raise HTTPException(404)
    return render(
        request,
        "auth/register.html",
        email="",
        name="",
        error=None,
        first=sessions.count_users(db) == 0,
    )


@router.post("/register")
def register(
    request: Request,
    email: str = Form(""),
    name: str = Form(""),
    password: str = Form(""),
    db: Database = bound(Database),
):
    if not _can_register(request, db):
        raise HTTPException(404)
    state = _state(request)
    first = sessions.count_users(db) == 0
    try:
        user = sessions.create_user(
            db,
            email,
            password,
            name=name,
            roles=("admin",) if first else (),
            min_length=state["min_password_length"],
        )
    except AccountError as e:
        return _form_page(
            request, "auth/register.html", 400, email=email, name=name, error=str(e), first=first
        )
    token = sessions.open_session(
        db, user, days=state["session_days"], user_agent=request.headers.get("user-agent", "")
    )
    return _signed_in(request, token, "/")
