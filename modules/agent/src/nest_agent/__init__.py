"""The agent: a site tells the keeper how it is, and does what the keeper asks of it.

Its API (see module.yml) answers only a bearer token whose SHA-256 the site was given in
its environment: the read token for status, events, checks and the list of actions; the
control token also to run an action. What it counts (requests, errors, events) is kept in
memory, since the process started: the keeper keeps the history.

A module offers the keeper an action by answering ``agent.actions`` with a list of
:class:`Action`: the trains module offers "trains.sync" (fetch the timetable now).

A module tells what waits for an admin by answering ``agent.attention`` with a list of
plain dicts: ``{"key": "comments.pending", "label": "Comments awaiting approval",
"count": 3, "oldest": datetime, "path": "/admin/comments/"}``. The status gives each
with its label in the site's languages and the age of the oldest, in hours: counts and
links only, never what was written.
"""

from __future__ import annotations

import collections
import logging
import os
import platform
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import nest
from nest import ModuleHost
from nest.host import module_state
from nest_agent import tokens

__all__ = ["Action"]

API = "1"
log = logging.getLogger("nest.agent")
api = APIRouter(prefix="/v1")


@dataclass
class Action:
    """Something the keeper may ask the site to do. ``run`` takes the application's Nest
    and returns a short text or a dict (it runs in a thread; one at a time per action)."""

    name: str
    title: str
    run: Any
    description: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- what it counts ---------------------------------------------------------------------


class Counter:
    """Requests and server errors since the start (a pure ASGI middleware feeds it)."""

    def __init__(self) -> None:
        self.requests = 0
        self.errors = 0
        self.last_error: str | None = None
        self.slow = 0  # answers that took more than a second


class Counting:
    def __init__(self, app: Any, counter: Counter) -> None:
        self.app = app
        self.counter = counter

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        counter, started, status = self.counter, time.monotonic(), [500]

        async def sending(message: Any) -> None:
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            counter.requests += 1
            if status[0] >= 500:
                counter.errors += 1
                counter.last_error = now()
            if time.monotonic() - started > 1:
                counter.slow += 1


class Events(logging.Handler):
    """The site's recent warnings and errors, and what the agent itself notes."""

    def __init__(self, size: int) -> None:
        super().__init__(logging.WARNING)
        self.items: collections.deque[dict[str, Any]] = collections.deque(maxlen=max(10, size))
        self.serial = 0

    def note(self, level: str, source: str, text: str) -> None:
        self.serial += 1
        self.items.append(
            {"id": self.serial, "at": now(), "level": level, "source": source, "text": text[:2000]}
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                text += f" ({type(record.exc_info[1]).__name__}: {record.exc_info[1]})"
            self.note(record.levelname.lower(), record.name, text)
        except Exception:  # noqa: BLE001 - a log handler never raises
            pass


# --- the token ----------------------------------------------------------------------------

FAILURES_ALLOWED = 20  # bad tokens from one address in a minute, then 429
_failures: dict[str, tuple[int, float]] = {}


def _refused(request: Request) -> HTTPException:
    who = request.client.host if request.client else "?"
    count, since = _failures.get(who, (0, time.monotonic()))
    if time.monotonic() - since > 60:
        count, since = 0, time.monotonic()
    _failures[who] = (count + 1, since)
    if len(_failures) > 10_000:
        _failures.clear()
    return HTTPException(
        401, "a valid token is needed", headers={"WWW-Authenticate": 'Bearer realm="nest-agent"'}
    )


def _scope(request: Request) -> str:
    """The caller's scope ("read" or "control") from its bearer token, or 401/429."""
    who = request.client.host if request.client else "?"
    count, since = _failures.get(who, (0, 0.0))
    if count >= FAILURES_ALLOWED and time.monotonic() - since <= 60:
        raise HTTPException(
            429, "too many bad tokens; wait a minute", headers={"Retry-After": "60"}
        )
    scheme, _, secret = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not secret.strip():
        raise _refused(request)
    settings = module_state(request, "agent")["settings"]
    found = tokens.scope_of(
        secret.strip(),
        read=str(settings.get("read_token") or ""),
        control=str(settings.get("control_token") or ""),
    )
    if found is None:
        raise _refused(request)
    return found


def reader(request: Request) -> str:
    return _scope(request)


def controller(request: Request) -> str:
    found = _scope(request)
    if found != "control":
        raise HTTPException(403, "this token reads only; actions need the control token")
    return found


def reply(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


# --- what it tells ----------------------------------------------------------------------


def _migrations(the_nest: Any) -> dict[str, Any]:
    from nest_db import pending_migrations  # noqa: PLC0415

    try:
        return {"pending": pending_migrations(the_nest), "checked": True}
    except Exception as e:  # noqa: BLE001 - told, not raised
        return {"pending": [], "checked": False, "error": str(e)}


def _backups(the_nest: Any) -> dict[str, Any]:
    from nest.ops import _backups as found_backups  # noqa: PLC0415

    found = found_backups(the_nest.workspace)
    if not found:
        return {"count": 0, "last": None, "last_at": None, "age_hours": None}
    last = found[-1].stat()
    return {
        "count": len(found),
        "last": found[-1].name,
        "last_at": datetime.fromtimestamp(last.st_mtime, UTC).isoformat(timespec="seconds"),
        "age_hours": round((time.time() - last.st_mtime) / 3600, 1),
        "size_mb": round(last.st_size / 2**20, 1),
    }


def _databases(the_nest: Any) -> list[dict[str, Any]]:
    from nest.ops import _server_databases, _sqlite_files  # noqa: PLC0415

    out = [
        {"name": p.name, "kind": "sqlite", "size_mb": round(p.stat().st_size / 2**20, 1)}
        for p in _sqlite_files(the_nest)
        if p.exists()
    ]
    return out + [{"name": n, "kind": "server"} for n in _server_databases(the_nest)]


async def _checks(the_nest: Any) -> dict[str, bool]:
    import inspect  # noqa: PLC0415

    checks: dict[str, bool] = {}
    for provider in the_nest.bindings.providers():
        ping = getattr(provider.impl, "ping", None)
        try:
            if inspect.iscoroutinefunction(ping):
                checks[provider.name] = bool(await ping())
            elif callable(ping):
                checks[provider.name] = bool(await run_in_threadpool(ping))
        except Exception:  # noqa: BLE001 - a failed ping is a failed check
            checks[provider.name] = False
    return checks


def attention(the_nest: Any) -> list[dict[str, Any]]:
    """What waits for an admin, from every module that tells (agent.attention): those with
    something waiting, the label in each of the site's languages, the oldest's age."""
    out: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    languages = list(dict.fromkeys([*the_nest.admin_languages, *the_nest.site_languages])) or ["en"]
    for told in the_nest.gather("agent.attention"):
        for item in told or []:
            try:
                count = int(item.get("count") or 0)
            except (AttributeError, TypeError, ValueError):
                continue
            if count <= 0 or not item.get("key"):
                continue
            oldest = item.get("oldest")
            if isinstance(oldest, datetime):
                when = oldest if oldest.tzinfo else oldest.replace(tzinfo=UTC)
                age = round((now - when).total_seconds() / 3600, 1)
            else:
                age = None
            label = str(item.get("label") or item["key"])
            out.append(
                {
                    "key": str(item["key"])[:80],
                    "count": count,
                    "age_hours": age,
                    "path": str(item.get("path") or "")[:300],
                    "labels": {
                        lang: the_nest.catalogs.translator(lang)(label) for lang in languages
                    },
                }
            )
    return out


def actions(the_nest: Any) -> dict[str, Action]:
    state = the_nest.module_state["agent"]
    found = {a.name: a for a in state["builtin"]}
    for offered in the_nest.gather("agent.actions"):
        for a in offered or []:
            if isinstance(a, Action):
                found.setdefault(a.name, a)
    state.setdefault("known", {})
    for name, a in found.items():  # one lock per action name, kept across requests
        a.lock = state["known"].setdefault(name, a.lock)
    return found


@api.get("/status")
async def status(request: Request, scope: str = Depends(reader)):
    the_nest = request.app.state.nest
    state = module_state(request, "agent")
    counter: Counter = state["counter"]
    checks = await _checks(the_nest)
    migrations = await run_in_threadpool(_migrations, the_nest)
    backups = await run_in_threadpool(_backups, the_nest)
    disk = shutil.disk_usage(the_nest.workspace)
    states = list(the_nest.states.values())
    degraded = [s.name for s in states if s.state != "ready"]
    ok = all(checks.values()) and not migrations["pending"] and not degraded
    return reply(
        {
            "agent": API,
            "ok": ok,
            "app": {
                "name": the_nest.name,
                "title": the_nest.manifest.application.title
                if the_nest.manifest.application
                else the_nest.name,
                "version": the_nest.manifest.module.version,
            },
            "nest": nest.__version__,
            "python": platform.python_version(),
            "production": the_nest.production,
            "started_at": state["started_at"],
            "uptime_s": int(time.monotonic() - state["started"]),
            "pid": os.getpid(),
            "requests": {
                "total": counter.requests,
                "errors": counter.errors,
                "slow": counter.slow,
                "last_error": counter.last_error,
            },
            "events": {"last": state["events"].serial},
            "checks": checks,
            "modules": [
                {"name": s.name, "type": s.type, "version": s.version, "state": s.state}
                for s in states
            ],
            "degraded": degraded,
            "migrations": migrations,
            "backups": backups,
            "databases": await run_in_threadpool(_databases, the_nest),
            "disk": {
                "free_gb": round(disk.free / 2**30, 1),
                "total_gb": round(disk.total / 2**30, 1),
            },
            "scope": scope,
            "attention": await run_in_threadpool(attention, the_nest),
        }
    )


@api.get("/events")
def events(request: Request, after: int = 0, scope: str = Depends(reader)):
    found: Events = module_state(request, "agent")["events"]
    items = [e for e in list(found.items) if e["id"] > after]
    return reply({"events": items, "last": found.serial})


@api.get("/check")
async def check(request: Request, scope: str = Depends(reader)):
    from nest.ops import check as run_check  # noqa: PLC0415

    report = await run_in_threadpool(run_check, request.app.state.nest)
    return reply(
        {
            "failed": report.failed,
            "findings": [{"level": f.level, "text": f.text} for f in report.findings],
        }
    )


@api.get("/actions")
def action_list(request: Request, scope: str = Depends(reader)):
    found = actions(request.app.state.nest)
    return reply(
        {
            "actions": [
                {
                    "name": a.name,
                    "title": a.title,
                    "description": a.description,
                    "running": a.lock.locked(),
                }
                for a in found.values()
            ],
            "allowed": scope == "control",
        }
    )


@api.post("/actions/{name}")
async def action_run(request: Request, name: str, scope: str = Depends(controller)):
    the_nest = request.app.state.nest
    found = actions(the_nest).get(name)
    if found is None:
        return reply({"error": f"no action '{name}'"}, 404)
    if not found.lock.acquire(blocking=False):
        return reply({"error": f"'{name}' is already running"}, 409)
    events: Events = module_state(request, "agent")["events"]
    events.note("info", "agent", f"action {name} asked by the keeper")
    started = time.monotonic()
    try:
        result = await run_in_threadpool(found.run, the_nest)
    except Exception as e:  # noqa: BLE001 - the keeper is told what went wrong
        log.exception("action %s failed", name)
        return reply({"action": name, "ok": False, "error": str(e)}, 500)
    finally:
        found.lock.release()
    seconds = round(time.monotonic() - started, 1)
    events.note("info", "agent", f"action {name} done in {seconds}s")
    return reply({"action": name, "ok": True, "seconds": seconds, "result": result})


@api.get("/")
def index(scope: str = Depends(reader)):
    return reply(
        {
            "agent": API,
            "links": ["status", "events", "check", "actions"],
            "scope": scope,
        }
    )


# --- its own actions ----------------------------------------------------------------------


def _backup(the_nest: Any) -> dict[str, Any]:
    from nest.ops import backup  # noqa: PLC0415

    keep = int(the_nest.settings.get("agent.backup_keep") or 7)
    path = backup(the_nest, keep=max(1, keep))
    return {"archive": path.name, "size_mb": round(path.stat().st_size / 2**20, 1)}


def setup(host: ModuleHost) -> None:
    counter = Counter()
    handler = Events(int(host.settings.get("events") or 200))
    host.state.update(
        settings=host.settings,
        counter=counter,
        events=handler,
        started=time.monotonic(),
        started_at=now(),
        builtin=[
            Action(
                "backup",
                "Back up now",
                _backup,
                "The workspace in one archive (databases copied while the site runs).",
            )
        ],
    )
    host.add_middleware(Counting, counter=counter)
    root = logging.getLogger()

    @host.on_startup
    def listen() -> None:
        root.addHandler(handler)
        handler.note("info", "agent", f"{host.app_title} started (Nest {nest.__version__})")

    @host.on_shutdown
    def stop() -> None:
        root.removeHandler(handler)

    if host.route is not None:
        host.mount(api, csrf=False)  # a bearer token on every request; no cookie is read
