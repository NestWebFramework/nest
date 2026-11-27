"""The engine role: a module that keeps its state in one process (a game's worlds, say), served by
that process while gunicorn's workers serve the rest of the application.

``nest serve`` with such a module and several workers starts one more process, the
engine (``NEST_ROLE=engine``): the whole application, with the worlds open and ticking,
listening on a Unix socket in the workspace (``run/engine.sock``) or at the address
``NEST_ENGINE_URL`` names. The workers (``NEST_ROLE=web``) make the same application
without opening the worlds, and pass to the engine, streamed both ways, every request for:

* the routes of the one-process modules and of the packages that are part of them or
  depend on them (``/joc``, ``/api/joc``),
* their pages in the admin panel (``/admin/<engine>``...),
* an event stream following one of their topics (``/_nest/events?topic=<engine>...``).

The engine answers only requests a worker signed (a token made from the application's
secret key), and believes the visitor's address and scheme the worker sends with them.
Everything else (the site, the forum, letters, accounts, assets) is served by the workers.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import parse_qsl

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("nest.engine")

ROLES = ("", "engine", "web")
TOKEN = b"x-nest-engine"
CLIENT = b"x-nest-client"
SCHEME = b"x-nest-scheme"
SERVED_BY = b"x-nest-process"
INTERNAL = (TOKEN, CLIENT, SCHEME)
HOP_BY_HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"trailers",
    b"transfer-encoding",
    b"upgrade",
}
MAX_BODY = 8 * 1024 * 1024  # a form or a JSON command; the game takes no uploads
OPEN_PATHS = ("/healthz", "/_nest/health")  # a probe asks the engine directly


def token(secret: str) -> str:
    """What a worker shows the engine: only processes that hold the secret key have it."""
    return hmac.new(secret.encode(), b"nest engine", hashlib.sha256).hexdigest()


def engine_units(plan: Any) -> set[str]:
    """The one-process modules, the packages that are part of them, and the modules that
    depend on them: what only the engine can serve."""
    hosts = {u.name for u in plan.units if getattr(u.entry.manifest, "one_process", False)}
    if not hosts:
        return set()
    out = set(hosts)
    for u in plan.units:
        m = u.entry.manifest
        if m.part_of in hosts or (u.entry.type == "module" and hosts & set(m.deps or {})):
            out.add(u.name)
    return out


def engine_paths(nest: Any) -> list[str]:
    """The path prefixes the engine serves: its modules' routes and admin pages."""
    units = engine_units(nest.plan)
    paths = []
    for u in nest.plan.units:
        route = u.instance.route if u.instance is not None else None
        if u.name in units and route:
            if route == "/":
                raise ValueError(
                    f"{u.name} is at /, so the engine would serve the whole site; give it a route"
                )
            paths.append(route.rstrip("/"))
    paths += [p.base for p in nest.admin_pages if p.module in units and p.base]
    return sorted(set(paths), key=len, reverse=True)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


async def _plain(send: Send, status: int, text: str, extra: list | None = None) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *(extra or [])],
        }
    )
    await send({"type": "http.response.body", "body": text.encode()})


class EngineProxy:
    """In a worker: the engine's requests go to the engine, the rest to the application."""

    def __init__(self, app: ASGIApp, *, nest: Any, url: str):
        self.app, self.nest, self.url = app, nest, url
        self.secret = token(nest.secret)
        self._paths: list[str] | None = None
        self._units: set[str] = set()
        self._client: Any = None

    def _mine(self, scope: Scope) -> bool:
        if self._paths is None:
            self._paths, self._units = engine_paths(self.nest), engine_units(self.nest.plan)
        path = scope["path"]
        if path == "/_nest/events":
            query = scope.get("query_string", b"").decode("latin-1")
            for key, name in parse_qsl(query):
                topic = self.nest.broker.find(name) if key == "topic" else None
                if topic is not None and topic.owner in self._units:
                    return True
            return False
        return any(path == p or path.startswith(p + "/") for p in self._paths)

    def _http(self) -> Any:
        if self._client is None:
            import httpx  # noqa: PLC0415 - only a worker with an engine needs it

            timeout = httpx.Timeout(30.0, read=None)  # an event stream reads for hours
            if self.url.startswith("unix:"):
                transport = httpx.AsyncHTTPTransport(uds=self.url[len("unix:") :])
                self._client = httpx.AsyncClient(
                    transport=transport, base_url="http://engine", timeout=timeout
                )
            else:
                self._client = httpx.AsyncClient(base_url=self.url, timeout=timeout)
        return self._client

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._mine(scope):
            await self.app(scope, receive, send)
            return
        await self._forward(scope, receive, send)

    async def _forward(self, scope: Scope, receive: Receive, send: Send) -> None:
        import httpx  # noqa: PLC0415

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > MAX_BODY:
                await _plain(send, 413, "Too large.")
                return
            if not message.get("more_body"):
                break
        headers = [
            (k, v)
            for k, v in scope["headers"]
            if k.lower() not in HOP_BY_HOP and k.lower() not in INTERNAL
        ]
        client = scope.get("client")
        headers += [
            (TOKEN, self.secret.encode()),
            (CLIENT, (client[0] if client else "").encode("latin-1")),
            (SCHEME, scope.get("scheme", "http").encode()),
        ]
        target = scope.get("raw_path") or scope["path"].encode()
        if scope.get("query_string"):
            target += b"?" + scope["query_string"]
        http = self._http()
        request = http.build_request(
            scope["method"], target.decode("latin-1"), headers=headers, content=bytes(body)
        )
        try:
            response = await http.send(request, stream=True)
        except httpx.TransportError:
            log.warning("the engine did not answer %s %s", scope["method"], scope["path"])
            await _plain(
                send, 503, "The game is starting; try again in a moment.", [(b"retry-after", b"5")]
            )
            return
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": [
                        (k.lower(), v)
                        for k, v in response.headers.raw
                        if k.lower() not in HOP_BY_HOP
                    ],
                }
            )
            await self._stream(response, receive, send)
        finally:
            await response.aclose()

    async def _stream(self, response: Any, receive: Receive, send: Send) -> None:
        """The engine's answer as it comes, until it ends or the visitor leaves."""

        async def pump() -> None:
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def gone() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass

        tasks = [asyncio.ensure_future(pump()), asyncio.ensure_future(gone())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        error = results[0]
        if isinstance(error, Exception) and not isinstance(
            error, (OSError, asyncio.CancelledError)
        ):
            log.warning("the engine's answer broke off: %s", error)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


class EngineGate:
    """In the engine: only a worker's requests, with the visitor's address and scheme."""

    def __init__(self, app: ASGIApp, *, secret: str):
        self.app, self.secret = app, token(secret)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] not in OPEN_PATHS:
            if not hmac.compare_digest(_header(scope, TOKEN), self.secret):
                await _plain(send, 403, "The engine answers its workers only.")
                return
            client = _header(scope, CLIENT)
            scope["client"] = (client, 0) if client else None
            scope["scheme"] = _header(scope, SCHEME) or scope.get("scheme", "http")
            scope["headers"] = [(k, v) for k, v in scope["headers"] if k not in INTERNAL]

        async def marked(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (SERVED_BY, b"engine")]
            await send(message)

        await self.app(scope, receive, marked)
