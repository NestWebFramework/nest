"""The keeper's servers: each one's host helper (nest-host), where the sites it acts on run.

/servers                every server, its helper asked at once: its host's name, its
                        sites, the actions it allows (and the helper of the settings, if any)
/servers/new            a server: its helper's address, token, Cloudflare Access client
/servers/{id}/edit      change it (an empty token or secret keeps the one it has); forget it
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, render
from nest.host import module_state
from nest_keeper import admin, host, keeper, sites


def _seal(request: Request) -> str:
    return module_state(request, "keeper")["seal"]


def _base(request: Request) -> str:
    return admin_url(request, "keeper")


async def _ask(h: host.Helper | None) -> dict[str, Any]:
    if h is None:
        return {"ok": False, "problem": "its token cannot be read: give it again"}
    answer = await run_in_threadpool(host.about, h)
    if answer.code == 200 and isinstance(answer.data, dict):
        return {"ok": True, **answer.data}
    return {"ok": False, "problem": answer.problem or "no answer"}


@admin.get("/servers")
async def server_list(
    request: Request, user: CurrentUser = Depends(keeper), db: Database = bound(Database)
):
    seal = _seal(request)
    found = await run_in_threadpool(host.servers, db, seal)
    helpers = [await run_in_threadpool(host.helper_of, db, seal, x.id) for x in found]
    answers = await asyncio.gather(*(_ask(h) for h in helpers))
    settings_helper = host.helper(module_state(request, "keeper")["settings"])
    return render(
        request,
        "keeper/servers.html",
        servers=list(zip(found, answers, strict=True)),
        settings_helper=settings_helper,
        settings_answer=await _ask(settings_helper) if settings_helper else None,
        base=_base(request),
    )


def _form(request: Request, *, server: Any = None, error: str = "", values: Any = None, code=200):
    return render(
        request,
        "keeper/server_form.html",
        status_code=code,
        server=server,
        error=error,
        values=values or {},
        base=_base(request),
    )


@admin.get("/servers/new")
def server_new(request: Request, user: CurrentUser = Depends(keeper)):
    return _form(request)


@admin.post("/servers/new")
def server_create(
    request: Request,
    name: str = Form(""),
    url: str = Form(""),
    token: str = Form(""),
    access_id: str = Form(""),
    access_secret: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    try:
        host.add_server(
            db,
            _seal(request),
            name=name,
            url=url,
            token=token,
            access_id=access_id,
            access_secret=access_secret,
        )
    except sites.SiteError as e:  # never a secret back in the page
        values = {"name": name, "url": url, "access_id": access_id}
        return _form(request, error=str(e), values=values, code=400)
    return RedirectResponse(f"{_base(request)}/servers", status_code=303)


def _server_or_404(db: Database, seal: str, server_id: int) -> host.Server:
    found = host.server(db, seal, server_id)
    if found is None:
        raise HTTPException(404)
    return found


@admin.get("/servers/{server_id:int}/edit")
def server_edit_form(
    request: Request,
    server_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    found = _server_or_404(db, _seal(request), server_id)
    values = {"name": found.name, "url": found.url, "access_id": found.access_id}
    return _form(request, server=found, values=values)


@admin.post("/servers/{server_id:int}/edit")
def server_edit(
    request: Request,
    server_id: int,
    name: str = Form(""),
    url: str = Form(""),
    token: str = Form(""),
    access_id: str = Form(""),
    access_secret: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    found = _server_or_404(db, seal, server_id)
    try:
        host.edit_server(
            db,
            seal,
            server_id,
            name=name,
            url=url,
            token=token,
            access_id=access_id,
            access_secret=access_secret,
        )
    except sites.SiteError as e:
        values = {"name": name, "url": url, "access_id": access_id}
        return _form(request, server=found, error=str(e), values=values, code=400)
    return RedirectResponse(f"{_base(request)}/servers", status_code=303)


@admin.post("/servers/{server_id:int}/delete")
def server_delete(
    request: Request,
    server_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    if not host.remove_server(db, server_id):
        raise HTTPException(404)
    return RedirectResponse(f"{_base(request)}/servers", status_code=303)
