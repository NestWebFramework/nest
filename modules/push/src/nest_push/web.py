"""The push module over HTTP (scripts send JSON, with the page's CSRF token as a header):

    GET  <route>/cheie        the site's public key, for PushManager.subscribe()
    POST <route>/abonare      a browser's subscription (PushSubscription.toJSON())
    POST <route>/dezabonare   {endpoint}: forget it, and all that waits for it
    POST <route>/alerte       {endpoint}: what waits for it
    POST <route>/anulare      {endpoint, ref}: forget one
The endpoint travels in the body, never in an address (it would land in logs).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from nest_db import Database

from nest import bound
from nest.host import module_state
from nest_push import store, webpush

router = APIRouter()


def _host(request: Request) -> Any:
    return module_state(request, "push")["host"]


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400) from None
    if not isinstance(data, dict):
        raise HTTPException(400)
    return data


@router.get("/cheie")
def public_key(request: Request):
    return JSONResponse(
        {"key": webpush.public(webpush.keys(_host(request).workspace))},
        headers={"cache-control": "public, max-age=3600"},
    )


@router.post("/abonare")
async def subscribe(request: Request, db: Database = bound(Database)):
    sub = store.valid(await _body(request))
    if sub is None:
        raise HTTPException(400, "not a push subscription of a known push service")
    store.subscribe(db, store.key_of(_host(request)), sub)
    return JSONResponse({"ok": True}, headers={"cache-control": "no-store"})


@router.post("/dezabonare")
async def unsubscribe(request: Request, db: Database = bound(Database)):
    store.unsubscribe(db, str((await _body(request)).get("endpoint") or ""))
    return JSONResponse({"ok": True}, headers={"cache-control": "no-store"})


@router.post("/alerte")
async def waiting(request: Request, db: Database = bound(Database)):
    endpoint = str((await _body(request)).get("endpoint") or "")
    items = store.waiting(db, store.key_of(_host(request)), endpoint)
    return JSONResponse(
        {
            "alerts": [
                {
                    "ref": x["ref"],
                    "due": x["due"].isoformat(),
                    "title": (x.get("message") or {}).get("title", ""),
                    "body": (x.get("message") or {}).get("body", ""),
                    "data": x.get("data") or {},
                }
                for x in items
            ]
        },
        headers={"cache-control": "no-store"},
    )


@router.post("/anulare")
async def cancel(request: Request, db: Database = bound(Database)):
    data = await _body(request)
    done = store.cancel(db, str(data.get("endpoint") or ""), str(data.get("ref") or ""))
    return JSONResponse({"ok": done}, headers={"cache-control": "no-store"})
