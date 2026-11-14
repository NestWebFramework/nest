"""The keeper's REST API: what Nest is and holds, for another orchestrator. Read-only, versioned.

    GET /api/v1/              what is here
    GET /api/v1/ecosystem     Nest itself: its name, kind, version, the package types it knows
    GET /api/v1/apps          every application: version, port, whether it runs, its problems
    GET /api/v1/apps/{name}   one application: its plan (packages in start order, routes,
                              bindings, notes) and problems
    GET /api/v1/packages      every package Nest can see, by type

Every call carries a token: ``Authorization: Bearer nk_...``, made in the keeper's admin
panel (or with ``nest keeper token``), kept only as a hash, revocable. Cookies are not
read here, so a signed-in browser cannot be made to call the API. An address that sends
bad tokens again and again is answered 429 for a while. Answers are not cached.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from nest_db import Database

import nest
from nest import bound
from nest.catalog import Catalog
from nest.contract import load_contracts
from nest.host import module_state
from nest_keeper import tokens

api = APIRouter(prefix="/api/v1")
VERSION = "1"
FAILURES_ALLOWED = 20  # bad tokens from one address in a minute, then 429
_failures: dict[str, tuple[int, float]] = {}


def _refuse(request: Request) -> HTTPException:
    who = request.client.host if request.client else "?"
    count, since = _failures.get(who, (0, time.monotonic()))
    if time.monotonic() - since > 60:
        count, since = 0, time.monotonic()
    _failures[who] = (count + 1, since)
    if len(_failures) > 10_000:  # never grows without end
        _failures.clear()
    return HTTPException(
        401, "a valid token is needed", headers={"WWW-Authenticate": 'Bearer realm="nest-keeper"'}
    )


def token(request: Request, db: Database = bound(Database)) -> tokens.Token:
    """The caller's token, from its Authorization header: the API's only credential."""
    who = request.client.host if request.client else "?"
    count, since = _failures.get(who, (0, 0.0))
    if count >= FAILURES_ALLOWED and time.monotonic() - since <= 60:
        raise HTTPException(
            429, "too many bad tokens; wait a minute", headers={"Retry-After": "60"}
        )
    scheme, _, secret = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not secret:
        raise _refuse(request)
    found = tokens.check(db, secret.strip())
    if found is None or "read" not in found.scopes:
        raise _refuse(request)
    return found


def reply(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def _folders(request: Request) -> list[Any]:
    return module_state(request, "keeper")["folders"]


def _app(a: Any, *, full: bool = False) -> dict[str, Any]:
    out = {
        "name": a.name,
        "title": a.title,
        "version": a.version,
        "port": a.port,
        "source": a.source,
        "running": a.running,
        "packages": len(a.units),
        "problems": list(a.problems),
    }
    if full:
        out |= {"root": str(a.root), "units": a.units, "bindings": a.bindings, "notes": a.notes}
    return out


@api.get("/")
def index(t: tokens.Token = Depends(token)):
    return reply(
        {
            "api": VERSION,
            "links": {
                "ecosystem": "ecosystem",
                "apps": "apps",
                "app": "apps/{name}",
                "packages": "packages",
            },
            "token": {"name": t.name, "scopes": list(t.scopes)},
        }
    )


@api.get("/ecosystem")
def ecosystem(request: Request, t: tokens.Token = Depends(token)):
    contract = load_contracts()
    return reply(
        {
            "name": "nest",
            "kind": "web",
            "description": "A lightweight, manifest-driven host for web applications and their modules.",
            "version": nest.__version__,
            "api": VERSION,
            "ecosystems": list(contract.ecosystems),
            "types": {
                name: {"ecosystem": rule.ecosystem, "description": rule.description}
                for name, rule in sorted(contract.types.items())
            },
            "keeper": request.app.state.nest.name,
        }
    )


@api.get("/apps")
async def apps(request: Request, t: tokens.Token = Depends(token)):
    from nest_keeper import applications, probed

    found = await probed(await asyncio.to_thread(applications, _folders(request)))
    return reply({"apps": [_app(a) for a in found]})


@api.get("/apps/{name}")
async def app(request: Request, name: str, t: tokens.Token = Depends(token)):
    from nest_keeper import applications, probed

    found = {a.name: a for a in await asyncio.to_thread(applications, _folders(request))}
    if name not in found:
        return reply({"error": f"no application '{name}'"}, 404)
    (a,) = await probed([found[name]])
    return reply(_app(a, full=True))


@api.get("/packages")
def packages(t: tokens.Token = Depends(token)):
    catalog = Catalog.discover()
    return reply(
        {
            "packages": [
                {
                    "name": e.name,
                    "id": e.id,
                    "type": e.type,
                    "version": e.manifest.module.version,
                    "description": e.manifest.module.description,
                    "source": e.source,
                }
                for e in catalog
            ],
            "problems": list(catalog.problems),
        }
    )
