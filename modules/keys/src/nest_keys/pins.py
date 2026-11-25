"""A device's PIN, for a computer (or a shared one) without Windows Hello or Touch ID: after
`pin_idle_hours` without use the device's session is locked until its PIN is typed. The PIN
unlocks only a session already on this device; it is never a way in from another, where 4-8
digits could be guessed. Five wrong tries lock it for 15 minutes, ten sign the device out
(it comes back by its key or a passkey, and may set a new PIN).

The gate (PinGate) runs before everything: a request whose session's device is locked gets
the unlock page (a page) or a 401 (anything else). It reads the session cookie itself, so it
does not depend on where it stands among the middlewares.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from nest_auth import close_session_id, hash_password, token_id, verify_password
from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from nest_keys.models import DevicePin, utcnow

COOKIE = "nest_session"
LOCK_AFTER, SIGN_OUT_AFTER = 5, 10
LOCK_MINUTES = 15
TOUCH_EVERY = timedelta(minutes=1)  # how often a device's last use is written
CACHE_S = 30  # seconds a worker trusts what it read of a device


class PinError(ValueError):
    pass


def check(pin: str) -> str:
    pin = (pin or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise PinError("digits")
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise PinError("easy")  # 1111, 1234, 4321: the first ones anyone tries
    return pin


_cache: dict[str, tuple[float, DevicePin | None]] = {}


def forget(session_id: str = "") -> None:
    if session_id:
        _cache.pop(session_id, None)
    else:
        _cache.clear()


def of(db: Any, session_id: str) -> DevicePin | None:
    hit = _cache.get(session_id)
    if hit and hit[0] > time.time():
        return hit[1]
    with db.session() as s:
        row = s.get(DevicePin, session_id)
        if row is not None:
            s.expunge(row)
    if len(_cache) > 5000:
        _cache.clear()
    _cache[session_id] = (time.time() + CACHE_S, row)
    return row


def set_pin(db: Any, user_id: int, session_id: str, pin: str) -> None:
    pin = check(pin)
    with db.session() as s, s.begin():
        row = s.get(DevicePin, session_id)
        if row is None:
            row = DevicePin(id=session_id, user_id=user_id, created_at=utcnow())
            s.add(row)
        row.pin_hash = hash_password(pin)
        row.tries = 0
        row.locked_until = None
        row.last_active_at = utcnow()
    forget(session_id)


def remove(db: Any, user_id: int, session_id: str) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(DevicePin).where(DevicePin.id == session_id, DevicePin.user_id == user_id))
    forget(session_id)


def drop(db: Any, session_id: str) -> None:
    """This device's PIN, gone with its session (signing out)."""
    with db.session() as s, s.begin():
        s.execute(delete(DevicePin).where(DevicePin.id == session_id))
    forget(session_id)


def locked(row: DevicePin | None, idle_hours: float, now: datetime | None = None) -> bool:
    if row is None:
        return False
    now = now or utcnow()
    return now - row.last_active_at > timedelta(hours=idle_hours)


def touch(db: Any, session_id: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    with db.session() as s, s.begin():
        row = s.get(DevicePin, session_id)
        if row is not None:
            row.last_active_at = now
    forget(session_id)


def unlock(db: Any, session_id: str, pin: str) -> str:
    """ "ok", "wrong", "paused" (wait), "out" (the device was signed out)."""
    now = utcnow()
    user_id = 0
    with db.session() as s, s.begin():
        row = s.get(DevicePin, session_id)
        if row is None:
            return "ok"
        if row.locked_until and row.locked_until > now:
            return "paused"
        if verify_password((pin or "").strip(), row.pin_hash):
            row.tries = 0
            row.locked_until = None
            row.last_active_at = now
            result = "ok"
        else:
            row.tries += 1
            user_id = row.user_id
            if row.tries >= SIGN_OUT_AFTER:
                s.delete(row)
                result = "out"
            else:
                if row.tries % LOCK_AFTER == 0:
                    row.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                result = "wrong"
    forget(session_id)
    if result == "out":
        close_session_id(db, user_id, session_id)
    return result


def users_with(db: Any) -> set[int]:
    with db.session() as s:
        return set(s.scalars(select(DevicePin.user_id).distinct()))


def _cookie(scope: Scope) -> str:
    from http.cookies import SimpleCookie

    for key, value in scope.get("headers", []):
        if key == b"cookie":
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:  # noqa: BLE001 - a malformed cookie is no cookie
                continue
            if COOKIE in jar:
                return jar[COOKIE].value
    return ""


SKIP = (
    "/assets/",
    "/static/",
    "/healthz",
    "/_nest",
    "/favicon",
    "/robots.txt",
    "/sw.js",
    "/manifest",
)


class PinGate:
    """Locks a device whose PIN is due: pages go to the unlock page, the rest get a 401."""

    def __init__(self, app: ASGIApp, *, base: str, idle_hours: Any):
        self.app, self.base = app, base
        self.idle = idle_hours  # a callable: the setting, read when used
        self.open = (f"{base}/pin", f"{base}/iesire")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(SKIP + self.open):
            await self.app(scope, receive, send)
            return
        token = _cookie(scope)
        if not token or len(token) > 128:
            await self.app(scope, receive, send)
            return
        db = scope["app"].state.nest.bindings.get("nest.db")
        sid = token_id(token)
        row = await run_in_threadpool(of, db, sid)
        if row is None:
            await self.app(scope, receive, send)
            return
        now = utcnow()
        if locked(row, float(self.idle() or 12), now):
            await self._locked(scope, send)
            return
        if now - row.last_active_at > TOUCH_EVERY:
            await run_in_threadpool(touch, db, sid, now)
        await self.app(scope, receive, send)

    async def _locked(self, scope: Scope, send: Send) -> None:
        headers = {k: v for k, v in scope.get("headers", [])}
        accept = headers.get(b"accept", b"").decode("latin-1")
        page = scope["method"] == "GET" and "text/html" in accept and b"hx-request" not in headers
        unlock_at = f"{self.base}/pin"
        if page:
            path = scope["path"] + (
                ("?" + scope["query_string"].decode()) if scope.get("query_string") else ""
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [
                        (b"location", f"{unlock_at}?next={quote(path)}".encode()),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        body = json.dumps({"locked": True, "unlock": unlock_at}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"hx-redirect", unlock_at.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
