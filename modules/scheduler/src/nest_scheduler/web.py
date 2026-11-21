"""The scheduler's admin pages: every job, when it runs next and how it went; run one now,
pause or resume it; its runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from nest_db import Database

from nest import admin_url, bound, render
from nest.host import module_state
from nest_scheduler import store
from nest_scheduler.models import utcnow

admin = APIRouter()
editor = require_role("admin")


def _scheduler(request: Request) -> Any:
    return module_state(request, "scheduler")["scheduler"]


def _rows(request: Request, db: Database) -> list[dict[str, Any]]:
    scheduler = _scheduler(request)
    states = store.states(db)
    rows = []
    for key, job in sorted(scheduler.jobs.items()):
        st = states.get(key)
        rows.append({"job": job, "state": st, "when": scheduler.when(job)})
    return rows


@admin.get("/")
def index(request: Request, user: CurrentUser = Depends(editor), db: Database = bound(Database)):
    scheduler = _scheduler(request)
    return render(
        request,
        "scheduler/index.html",
        fragment="jobs",
        rows=_rows(request, db),
        problems=scheduler.problems,
        holder=store.lease_holder(db),
        now=utcnow(),
        zone=str(scheduler.zone()),
        base=admin_url(request, "scheduler"),
    )


@admin.get("/job/{key}")
def job(
    request: Request, key: str, user: CurrentUser = Depends(editor), db: Database = bound(Database)
):
    scheduler = _scheduler(request)
    found = scheduler.jobs.get(key)
    if found is None:
        raise HTTPException(404)
    return render(
        request,
        "scheduler/job.html",
        fragment="runs",
        job=found,
        when=scheduler.when(found),
        state=store.states(db).get(key),
        runs=store.runs(db, key, limit=100),
        now=utcnow(),
        base=admin_url(request, "scheduler"),
    )


@admin.post("/job/{key}/{action}")
def act(
    request: Request,
    key: str,
    action: str,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    if key not in _scheduler(request).jobs:
        raise HTTPException(404)
    changes = {"run": {"run_now": True}, "pause": {"paused": True}, "resume": {"paused": False}}
    if action not in changes:
        raise HTTPException(404)
    if not store.ask(db, key, **changes[action]):
        raise HTTPException(409, "the scheduler has not seen this job yet; wait a moment")
    back = request.headers.get("referer") or ""
    target = (
        admin_url(request, "scheduler", f"job/{key}")
        if "/job/" in back
        else admin_url(request, "scheduler") + "/"
    )
    return RedirectResponse(target, status_code=303)
