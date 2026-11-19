"""Toasts, carried from where a module says them to the page the person sees next.

``nest.toast(request, text, level)`` keeps the message in the request's scope. On the way
out this middleware looks at the answer:

* an htmx answer that stays on the page: the messages go in ``HX-Trigger`` (the
  ``nest:toast`` event), shown at once by toasts.js;
* anything else (a redirect, an htmx ``HX-Redirect``, a page): in a signed cookie, which
  the next page's region reads, and which goes away once read.

The cookie is signed (a forged one is ignored), short-lived, HttpOnly, and holds at
most five messages of 300 characters, escaped when shown like any template text.
"""

from __future__ import annotations

import base64
import json
from http.cookies import SimpleCookie
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nest import ModuleHost
from nest.toasts import LEVELS, MAX_TEXT

__all__ = ["ToastMiddleware"]

COOKIE = "nest_toast"
MAX_AGE = 120


def _clean(items: Any) -> list[dict[str, str]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            level = item.get("level") if item.get("level") in LEVELS else "info"
            out.append({"text": item["text"][:MAX_TEXT], "level": level})
    return out[:5]


class ToastMiddleware:
    """Pure ASGI (it never buffers a stream): reads the cookie in, writes the toasts out."""

    def __init__(self, app: ASGIApp, *, host: ModuleHost) -> None:
        self.app = app
        self.host = host

    def _read(self, scope: Scope) -> list[dict[str, str]]:
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                jar = SimpleCookie()
                try:
                    jar.load(value.decode("latin-1"))
                except Exception:  # noqa: BLE001 - a cookie header we cannot read holds no toast
                    return []
                if COOKIE in jar:
                    raw = self.host.unsign(jar[COOKIE].value)
                    if raw:
                        try:
                            return _clean(json.loads(base64.urlsafe_b64decode(raw.encode())))
                        except ValueError:
                            return []
        return []

    def _cookie(self, value: str, max_age: int) -> str:
        parts = [f"{COOKIE}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
        if self.host.production:
            parts.append("Secure")
        return "; ".join(parts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        incoming = self._read(scope)
        state["toasts_in"] = incoming
        had_cookie = bool(incoming) or any(
            n == b"cookie" and COOKIE.encode() in v for n, v in scope.get("headers", [])
        )
        htmx = any(n == b"hx-request" and v == b"true" for n, v in scope.get("headers", []))

        async def send_with_toasts(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                out = _clean(state.get("toasts_out") or [])
                shown = state.get("toasts_shown", False)
                status = message["status"]
                stays = htmx and "hx-redirect" not in headers and not 300 <= status < 400
                if out and stays:
                    trigger = {"nest:toast": {"items": out}}
                    headers.append("HX-Trigger", json.dumps(trigger, ensure_ascii=True))
                    out = []
                if out:  # for the next page, with any it has not shown yet
                    keep = [] if shown else incoming
                    data = base64.urlsafe_b64encode(json.dumps((keep + out)[:5]).encode()).decode()
                    headers.append("set-cookie", self._cookie(self.host.sign(data), MAX_AGE))
                elif shown and had_cookie:  # read by this page: gone
                    headers.append("set-cookie", self._cookie("", 0))
                # an answer that neither read nor said one (a stylesheet, a picture fetched
                # while the page loads) leaves the cookie alone
            await send(message)

        await self.app(scope, receive, send_with_toasts)


def setup(host: ModuleHost) -> None:
    host.add_middleware(ToastMiddleware, host=host)

    @host.context
    def _toasts(request: Any) -> dict[str, Any]:
        def toasts() -> list[dict[str, str]]:
            """The messages waiting for this page; reading them is what clears them."""
            state = request.scope.setdefault("state", {})
            state["toasts_shown"] = True
            waiting = list(state.get("toasts_in") or [])
            mine = state.get("toasts_out") or []  # said while making this very page
            state["toasts_out"] = []
            return (waiting + mine)[:5]

        return {"toasts": toasts}
