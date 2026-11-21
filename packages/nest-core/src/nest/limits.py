"""How much a request may send: its body, at most ``application.max_body_mb`` MB
(``NEST_MAX_BODY_MB`` in the environment wins; 32 by default).

The limit is kept before anything reads a body: a request that says it is larger
(Content-Length) is refused with 413 before a byte of it is read; one that does not say
(chunked) is counted as it comes and stopped at the limit, with the same 413. So nobody,
signed in or not, can make the site spool a body larger than that to its disk (a form's
CSRF token is read from its body, before who sent it is known).
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MB = 32


class BodyLimit:
    def __init__(self, app: ASGIApp, *, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                size = -1
            if size < 0 or size > self.limit:
                await _refuse(send, self.limit)
                return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:  # more than it said, or it did not say
                    raise HTTPException(413, _said(self.limit))
            return message

        await self.app(scope, counted, send)


def _said(limit: int) -> str:
    return f"A request may send at most {limit // 2**20} MB."


async def _refuse(send: Send, limit: int) -> None:
    body = _said(limit).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def limit_of(application: object, environ: dict[str, str]) -> int:
    """The body limit, in bytes: the environment's, else the application's, else 32 MB."""
    raw = environ.get("NEST_MAX_BODY_MB", "").strip()
    if raw.isdigit():
        return int(raw) * 2**20
    mb = getattr(application, "max_body_mb", None) if application is not None else None
    return int(mb if mb is not None else DEFAULT_MB) * 2**20
