"""The panel's modules page: what the application is made of, and what may change.

Core modules (and what they or the theme need) are shown locked. The others may be
disabled (their data stays), enabled again, or uninstalled (their data and settings go,
after a backup); a module installed but not used may be added, at a route. Every change
goes through nest.modules.change: planned first, backed up, made with the new modules
(their migrations run), undone if the application cannot start that way, then applied to
the running site (nest serve's workers reloaded one by one, or, under nest run, the
application made again in place). Each change is written in the workspace's log, shown
here. Only administrators reach it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from nest_auth import CurrentUser, require_role
from starlette.concurrency import run_in_threadpool

from nest import is_htmx, render, toast, translator
from nest.modules import ChangeError, change, history, reload_app, status

router = APIRouter()
admin_only = require_role("admin")
ACTIONS = ("enable", "disable", "uninstall")
GROUPS = ("core", "enabled", "disabled", "available")


def _page(
    request: Request,
    *,
    steps: list[str] | None = None,
    problems: list[str] | None = None,
    status_code: int = 200,
) -> Any:
    nest = request.app.state.nest
    rows = status(_app_dir(nest), nest.environ)
    running = {u.name for u in nest.plan.units}
    pending = [
        r.name
        for r in rows
        if (r.state == "enabled" and r.name not in running)
        or (r.state in ("disabled", "available") and r.name in running)
    ]
    groups = {g: [r for r in rows if r.state == g] for g in GROUPS}
    return render(
        request,
        "admin/modules.html",
        fragment="panel" if is_htmx(request) else None,
        groups=groups,
        pending=pending,
        steps=steps or [],
        problems=problems or [],
        log=history(nest.workspace, 15),
        status_code=status_code,
    )


def _app_dir(nest: Any) -> Path:
    return Path(nest.plan.app.manifest.root)


@router.get("/modules")
def modules_page(request: Request, user: CurrentUser = Depends(admin_only)):
    return _page(request)


@router.post("/modules/{name}/{action}")
async def modules_change(
    request: Request, name: str, action: str, user: CurrentUser = Depends(admin_only)
):
    if action not in ACTIONS:
        raise HTTPException(404)
    nest = request.app.state.nest
    t = translator(request)
    form = await request.form()
    if action == "uninstall" and str(form.get("confirm", "")).strip() != name:
        return _page(
            request,
            problems=[t("Type the module's name, {name}, to uninstall it.", name=name)],
            status_code=400,
        )
    route = str(form.get("route", "")).strip() or None
    if route and not route.startswith("/"):
        route = "/" + route
    steps: list[str] = []

    def say(line: str) -> None:  # nest.modules speaks English; the panel, the reader's language
        if line.startswith("backed up to "):
            steps.append(t("A backup was made: {path}", path=line.removeprefix("backed up to ")))

    try:
        await run_in_threadpool(
            lambda: change(
                _app_dir(nest),
                dict(nest.environ),
                routes={name: route} if route else None,
                reload=False,
                say=say,
                who=user.email,
                **{action: [name]},
            )
        )
    except ChangeError as e:
        return _page(request, problems=e.problems, status_code=400)
    done = {
        "enable": t("{name} is enabled.", name=name),
        "disable": t("{name} is disabled; its data is kept.", name=name),
        "uninstall": t("{name} is uninstalled; its data and settings are gone.", name=name),
    }[action]
    steps.append(done)
    how = reload_app(nest)
    if how:
        steps.append(t("The site is reloading to apply it."))
    else:
        steps.append(t("It applies when the site is restarted."))
    toast(request, done)
    return _page(request, steps=steps)
