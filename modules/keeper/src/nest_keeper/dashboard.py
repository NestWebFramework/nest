"""The keeper's dashboard: the deployed sites it watches through their agents.

/                       every site: up or down and since when, uptime over 24 hours
                        and 7 days, answer time, versions, pending migrations, last
                        backup (refreshed every 15 seconds)
/sites/new              watch a site: its address, its agent's, the agent's token
/sites/{id}             one site: its status, last checks, recent events, `nest check`,
                        the actions its agent allows (the control token) and who ran which
/sites/{id}/edit        change it, pause it, give a new token; or stop watching it
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


@admin.get("/")
def dashboard(
    request: Request, user: CurrentUser = Depends(keeper), db: Database = bound(Database)
):
    found = sites.listing(db, _seal(request), recent=40)
    counts = {
        k: sum(1 for s in found if s.state == k)
        for k in ("up", "warn", "down", "unknown", "paused")
    }
    return render(
        request,
        "keeper/sites.html",
        fragment="sites",
        sites=found,
        counts=counts,
        base=_base(request),
    )


def _form(
    request: Request,
    *,
    site: Any = None,
    error: str | None = None,
    values: Any = None,
    status_code: int = 200,
):
    return render(
        request,
        "keeper/site_form.html",
        status_code=status_code,
        site=site,
        error=error,
        values=values or {},
        base=_base(request),
    )


@admin.get("/sites/new")
def site_new(request: Request, user: CurrentUser = Depends(keeper)):
    return _form(request)


@admin.post("/sites/new")
async def site_create(
    request: Request,
    name: str = Form(""),
    url: str = Form(""),
    agent: str = Form(""),
    token: str = Form(""),
    host_site: str = Form(""),
    kind: str = Form("agent"),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    try:
        site_id = sites.add(
            db,
            seal,
            name=name,
            url=url,
            agent=agent,
            token=token,
            host_site=host_site,
            kind=kind,
        )
    except sites.SiteError as e:
        # never the token, back in a page
        values = {"name": name, "url": url, "agent": agent, "host_site": host_site, "kind": kind}
        return _form(request, error=str(e), values=values, status_code=400)
    await run_in_threadpool(sites.check, db, seal, site_id)  # its first check, at once
    return RedirectResponse(f"{_base(request)}/sites/{site_id}", status_code=303)


def _site_or_404(db: Database, seal: str, site_id: int) -> sites.Site:
    found = sites.one(db, seal, site_id)
    if found is None:
        raise HTTPException(404)
    return found


@admin.get("/sites/{site_id:int}")
async def site_detail(
    request: Request,
    site_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    site = await run_in_threadpool(_site_or_404, db, seal, site_id)
    events, offered = [], {}
    problems: list[str] = []
    if site.enabled and site.kind == "agent":
        _s, token = await run_in_threadpool(sites.token_of, db, seal, site_id)
        if token:
            got_events, got_actions = await asyncio.gather(
                run_in_threadpool(sites.call, site.agent, token, "events"),
                run_in_threadpool(sites.call, site.agent, token, "actions"),
            )
            if got_events.code == 200 and isinstance(got_events.data, dict):
                events = list(reversed(got_events.data.get("events") or []))[:50]
            elif got_events.problem:
                problems.append(got_events.problem)
            if got_actions.code == 200 and isinstance(got_actions.data, dict):
                offered = got_actions.data
    return render(
        request,
        "keeper/site.html",
        fragment="live",
        site=site,
        events=events,
        offered=offered,
        problems=problems,
        server=await _server(request, site),
        log=await run_in_threadpool(sites.actions_log, db, site_id),
        result=None,
        findings=None,
        base=_base(request),
    )


@admin.post("/sites/{site_id:int}/check")
async def site_check(
    request: Request,
    site_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    await run_in_threadpool(_site_or_404, db, seal, site_id)
    await run_in_threadpool(sites.check, db, seal, site_id)
    return RedirectResponse(f"{_base(request)}/sites/{site_id}", status_code=303)


@admin.get("/sites/{site_id:int}/findings")
async def site_findings(
    request: Request,
    site_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    """What production needs, as the site sees it (its agent runs `nest check`)."""
    seal = _seal(request)
    site, token = await run_in_threadpool(sites.token_of, db, seal, site_id)
    if token is None:
        raise HTTPException(409, "no readable token for this site")
    answer = await run_in_threadpool(sites.call, site.agent, token, "check")
    findings = (
        answer.data
        if answer.code == 200 and isinstance(answer.data, dict)
        else {"error": answer.problem}
    )
    return render(
        request, "keeper/site_findings.html", site=site, findings=findings, base=_base(request)
    )


@admin.post("/sites/{site_id:int}/actions/{action}")
async def site_action(
    request: Request,
    site_id: int,
    action: str,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    site = await run_in_threadpool(_site_or_404, db, seal, site_id)
    who = user.email or f"user #{user.id}"
    answer = await run_in_threadpool(sites.run_action, db, seal, site.id, action, who)
    data = answer.data if isinstance(answer.data, dict) else {}
    result = {
        "action": action,
        "ok": answer.code == 200,
        "text": data.get("result") if answer.code == 200 else (data.get("error") or answer.problem),
        "seconds": data.get("seconds"),
    }
    return render(
        request,
        "keeper/site.html",
        status_code=200 if result["ok"] else 502,
        site=site,
        events=[],
        offered={},
        problems=[],
        server=None,
        log=await run_in_threadpool(sites.actions_log, db, site_id),
        result=result,
        findings=None,
        base=_base(request),
    )


@admin.get("/sites/{site_id:int}/edit")
def site_edit_form(
    request: Request,
    site_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    site = _site_or_404(db, _seal(request), site_id)
    return _form(
        request,
        site=site,
        values={
            "name": site.name,
            "url": site.url,
            "agent": site.agent,
            "host_site": site.host_site,
        },
    )


@admin.post("/sites/{site_id:int}/edit")
def site_edit(
    request: Request,
    site_id: int,
    name: str = Form(""),
    url: str = Form(""),
    agent: str = Form(""),
    token: str = Form(""),
    enabled: bool = Form(False),
    host_site: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    seal = _seal(request)
    site = _site_or_404(db, seal, site_id)
    try:
        sites.edit(
            db,
            seal,
            site_id,
            name=name,
            url=url,
            agent=agent,
            token=token,
            enabled=enabled,
            host_site=host_site,
        )
    except sites.SiteError as e:
        values = {"name": name, "url": url, "agent": agent, "host_site": host_site}
        return _form(request, site=site, error=str(e), values=values, status_code=400)
    return RedirectResponse(f"{_base(request)}/sites/{site_id}", status_code=303)


@admin.post("/sites/{site_id:int}/delete")
def site_delete(
    request: Request,
    site_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    if not sites.remove(db, site_id):
        raise HTTPException(404)
    return RedirectResponse(f"{_base(request)}/", status_code=303)


# --- the server, through the host helper (nest-host) -------------------------------------


def _helper(request: Request) -> host.Helper | None:
    return host.helper(module_state(request, "keeper")["settings"])


async def _server(request: Request, site: sites.Site) -> dict[str, Any] | None:
    """The site's container as the host helper sees it (None: no helper, or no name)."""
    h = _helper(request)
    if not site.host_site:
        return None
    if h is None:
        return {"configured": False, "state": None, "problem": ""}
    answer = await run_in_threadpool(host.state, h, site.host_site)
    ok = answer.code == 200 and isinstance(answer.data, dict)
    return {
        "configured": True,
        "state": answer.data if ok else None,
        "problem": "" if ok else answer.problem,
        "actions": host.ACTIONS,
    }


def _server_site(request: Request, db: Database, site_id: int) -> tuple[sites.Site, host.Helper]:
    site = _site_or_404(db, _seal(request), site_id)
    h = _helper(request)
    if h is None or not site.host_site:
        raise HTTPException(409, "no host helper for this site (host_url, host_token, its name)")
    return site, h


@admin.post("/sites/{site_id:int}/server/{action}")
async def server_action(
    request: Request,
    site_id: int,
    action: str,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    """Ask the host helper to restart (back up, upgrade, roll back...) the site's container."""
    if action not in host.ACTIONS:
        raise HTTPException(404)
    site, h = await run_in_threadpool(_server_site, request, db, site_id)
    who = user.email or f"user #{user.id}"
    answer = await run_in_threadpool(host.start, h, site.host_site, action, who)
    data = answer.data if isinstance(answer.data, dict) else {}
    started = answer.code == 202 and data.get("id")
    note = f"job {data['id']}" if started else (data.get("error") or answer.problem)
    await run_in_threadpool(
        sites.note_action, db, site.id, f"server.{action}", who, bool(started), note
    )
    if started:
        return RedirectResponse(
            f"{_base(request)}/sites/{site_id}/server/jobs/{data['id']}", status_code=303
        )
    if answer.code == 409 and data.get("job"):  # one is running: show it
        return RedirectResponse(
            f"{_base(request)}/sites/{site_id}/server/jobs/{data['job']}", status_code=303
        )
    return render(
        request,
        "keeper/server_job.html",
        status_code=502,
        site=site,
        job=None,
        problem=note or "the host helper did not start it",
        base=_base(request),
    )


@admin.get("/sites/{site_id:int}/server/jobs/{job_id}")
async def server_job(
    request: Request,
    site_id: int,
    job_id: str,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    site, h = await run_in_threadpool(_server_site, request, db, site_id)
    answer = await run_in_threadpool(host.job, h, job_id)
    found = answer.data if answer.code == 200 and isinstance(answer.data, dict) else None
    if found is not None and found.get("site") != site.host_site:
        raise HTTPException(404)
    return render(
        request,
        "keeper/server_job.html",
        fragment="job",
        site=site,
        job=found,
        problem="" if found else answer.problem,
        base=_base(request),
    )


@admin.get("/sites/{site_id:int}/server/logs")
async def server_logs(
    request: Request,
    site_id: int,
    lines: int = 200,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    site, h = await run_in_threadpool(_server_site, request, db, site_id)
    answer = await run_in_threadpool(host.logs, h, site.host_site, max(20, min(1000, lines)))
    data = answer.data if isinstance(answer.data, dict) else {}
    return render(
        request,
        "keeper/server_logs.html",
        site=site,
        text=data.get("lines") or "",
        problem="" if answer.code == 200 else answer.problem,
        lines=lines,
        base=_base(request),
    )
