"""The panel's modules page: what the site is made of, its versions, and what may change.

Four tabs:

* **Installed**: every module, by state (core, enabled, disabled, installed and not used),
  with the version it runs (the image's, or one chosen here), the registry's newest, and
  where its database stands. Enable, disable, uninstall, add at an address; Update.
* **Updates**: what the registry has newer, each with Update, and Update all.
* **Registry**: the Nest registry's packages that work with this site's Nest, searched;
  a module not installed is added from here (its version kept in the workspace, with any
  Nest package it needs), then enabled at an address.
* **History**: every change, done or refused.

A module's own page shows its versions (choose another, up or down, or the image's again)
and its migrations (up or down to a revision, after a backup).

Enabling, disabling, uninstalling go through nest.modules.change; versions and
migrations through nest.versions, in a process of their own (``nest modules … version``),
then the running site is reloaded (nest serve's workers one by one, or the application
made again under nest run). Every change is checked first, backed up, undone if the site
cannot start that way, and logged. Only administrators reach it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from nest_auth import CurrentUser, require_role
from starlette.concurrency import run_in_threadpool

from nest import is_htmx, render, toast, translator
from nest.modules import ChangeError, change, history, reload_app, status
from nest_admin import changes

router = APIRouter()
admin_only = require_role("admin")
ACTIONS = ("enable", "disable", "uninstall")
GROUPS = ("core", "enabled", "disabled", "available")
TABS = ("installed", "updates", "registry", "history")
REGISTRY_TTL = 300.0  # seconds the registry's catalog is kept between looks


def _app_dir(nest: Any) -> Path:
    return Path(nest.plan.app.manifest.root)


# --- the registry, looked at now and then --------------------------------------------------


def _offers(request: Request, *, fresh: bool = False) -> tuple[dict[str, Any], list[str]]:
    """The registry's packages that work with this nest-core, by name (each its newest),
    kept a few minutes; and what went wrong asking, if anything."""
    from nest.packages import PackageError, remote_offers  # noqa: PLC0415

    state = request.app.state.nest.module_state.setdefault("admin", {})
    cached = state.get("registry")
    if cached and not fresh and time.monotonic() - cached[0] < REGISTRY_TTL:
        return cached[1], cached[2]
    try:
        offers, problems = remote_offers(request.app.state.nest.environ), []
    except PackageError as e:
        offers, problems = {}, e.problems
    except Exception as e:  # noqa: BLE001 - the page still shows what is installed
        offers, problems = {}, [str(e)]
    state["registry"] = (time.monotonic(), offers, problems)
    return offers, problems


def _registry_url(request: Request) -> str:
    from nest.remote import registry_url  # noqa: PLC0415

    return registry_url(request.app.state.nest.environ)


# --- what the page shows --------------------------------------------------------------------


def _versions(request: Request, offers: dict[str, Any]) -> dict[str, Any]:
    """The site's packages' versions (nest.versions.installed), by name."""
    from nest import versions  # noqa: PLC0415

    nest = request.app.state.nest
    items = {n: {"version": o.version} for n, o in offers.items()}
    try:
        return {v.name: v for v in versions.installed(_app_dir(nest), nest.environ, offers=items)}
    except Exception:  # noqa: BLE001 - a site run from its own folder: no versions to show
        return {}


def _database(request: Request, names: list[str]) -> dict[str, Any]:
    """Where each running module's tables stand: current, behind (migrations to apply)."""
    from nest import versions  # noqa: PLC0415

    nest = request.app.state.nest
    out = {}
    for name in names:
        try:
            info = versions.migrations(nest, name)
        except Exception:  # noqa: BLE001 - shown as unknown
            info = None
        if info is not None:
            out[name] = info
    return out


def _page(
    request: Request,
    *,
    tab: str = "installed",
    steps: list[str] | None = None,
    problems: list[str] | None = None,
    status_code: int = 200,
    q: str = "",
    kind: str = "",
    category: str = "",
    everything: bool = False,
    place: str = "",
) -> Any:
    from nest.versions import updates  # noqa: PLC0415

    nest = request.app.state.nest
    tab = tab if tab in TABS else "installed"
    rows = status(_app_dir(nest), nest.environ)
    running = {u.name for u in nest.plan.units}
    pending = [
        r.name
        for r in rows
        if (r.state == "enabled" and r.name not in running)
        or (r.state in ("disabled", "available") and r.name in running)
    ]
    offers, registry_problems = _offers(request)
    versions = _versions(request, offers)
    newer = updates(list(versions.values()))
    installed_names = {v.name for v in versions.values()} | {r.name for r in rows}
    registry, hidden = [], 0
    app_type = _app_type(nest)
    if tab == "registry":
        needle = q.strip().lower()
        for o in sorted(offers.values(), key=lambda o: (o.category or "~", o.name)):
            # what this application can use: made for its type; not a part an engine
            # brings, nor an interface or provider the server's administrator sets up
            usable = (
                o.fits_type(app_type) and not o.part_of and o.type not in ("interface", "provider")
            )
            if not usable and not everything:
                hidden += 1
                continue
            if category and o.category != category:
                continue
            if kind and o.type != kind:
                continue
            if needle and needle not in f"{o.name} {o.title} {o.description}".lower():
                continue
            registry.append({"offer": o, "installed": o.name in installed_names, "usable": usable})
    return render(
        request,
        "admin/modules.html",
        fragment="panel" if is_htmx(request) else None,
        tab=tab,
        groups={g: [r for r in rows if r.state == g] for g in GROUPS},
        versions=versions,
        database=_database(request, sorted(running)) if tab == "installed" else {},
        updates=newer,
        registry=registry,
        registry_problems=registry_problems,
        registry_url=_registry_url(request),
        kinds=sorted({o.type for o in offers.values()}),
        categories=sorted({o.category for o in offers.values() if o.category}),
        category=category,
        everything=everything,
        hidden=hidden,
        app_type=app_type,
        q=q,
        kind=kind,
        pending=pending,
        place=place,
        steps=steps or [],
        problems=problems or [],
        change=changes.read(nest),
        back=str(request.url.path) + (f"?tab={tab}" if tab != "installed" else ""),
        log=history(nest.workspace, 40),
        status_code=status_code,
    )


def _app_type(nest: Any) -> str:
    app = nest.plan.app.manifest.application
    return app.type if app is not None else "site"


@router.get("/modules")
def modules_page(
    request: Request,
    tab: str = "installed",
    q: str = "",
    kind: str = "",
    category: str = "",
    everything: str = "",
    user: CurrentUser = Depends(admin_only),
):
    return _page(request, tab=tab, q=q, kind=kind, category=category, everything=everything == "1")


@router.get("/modules/registry")
def modules_registry(request: Request, q: str = "", user: CurrentUser = Depends(admin_only)):
    """The registry tab (the old address of the registry's search)."""
    return _page(request, tab="registry", q=q)


# --- running a change in a process of its own ------------------------------------------------


def _run_nest(request: Request, args: list[str], who: str) -> tuple[bool, list[str]]:
    """``nest modules <app> <args>`` in a new process (the running site is never changed
    in place): whether it worked, and what it said (its ✓ and ✗ lines, and the others)."""
    nest = request.app.state.nest
    code = "import sys\nfrom nest.cli import main\nraise SystemExit(main(sys.argv[1:]))\n"
    command = [
        sys.executable,
        "-c",
        code,
        "modules",
        str(_app_dir(nest)),
        *args,
        "--no-reload",
        "--who",
        who,
    ]
    env = {**os.environ, **nest.environ}
    done = subprocess.run(  # noqa: S603 - our interpreter, our arguments
        command, env=env, capture_output=True, text=True, timeout=1800, check=False
    )
    lines = [ln for ln in (done.stdout + "\n" + done.stderr).splitlines() if ln.strip()]
    problems = [ln.removeprefix("✗ ").strip() for ln in lines if ln.startswith("✗")]
    if done.returncode != 0 and not problems:
        problems = lines[-8:] or [f"exit {done.returncode}"]
    said = [ln for ln in lines if not ln.startswith("✗") and not ln.startswith("INFO")]
    return done.returncode == 0, problems or said


def _after(request: Request, done: list[str], tab: str, place: str = "") -> Any:
    t = translator(request)
    how = reload_app(request.app.state.nest)
    steps = [
        *done,
        t("The site is reloading to apply it.")
        if how
        else t("It applies when the site is restarted."),
    ]
    request.app.state.nest.module_state.setdefault("admin", {}).pop("registry", None)
    toast(request, t("Done."))
    return _page(request, tab=tab, steps=steps, place=place)


async def _versions_change(
    request: Request, wanted: dict[str, str], user: CurrentUser, tab: str
) -> Any:
    args = ["version", *[f"{n}={v}" for n, v in wanted.items()]]
    if not _start(request, args, user, tab=tab):
        return _page(request, tab=tab, problems=[_busy(request)], status_code=409)
    return _page(request, tab=tab)


def _start(request: Request, args: list[str], user: CurrentUser, **where: str) -> bool:
    """A version change begun in the background (see changes.py); False when another runs."""
    import asyncio  # noqa: PLC0415

    nest = request.app.state.nest
    nest.module_state.setdefault("admin", {}).pop("registry", None)
    return (
        changes.start(
            nest,
            lambda a, who: _run_nest(request, a, who),
            args,
            user.email,
            loop=asyncio.get_running_loop(),
            **where,
        )
        is not None
    )


def _busy(request: Request) -> str:
    return translator(request)("Another change is under way: wait until it is done.")


@router.get("/modules/_change")
def change_state(request: Request, user: CurrentUser = Depends(admin_only)):
    """The change under way, polled by the page: still running, done (the page then reloads
    once the workers are made again), or what went wrong."""
    from fastapi.responses import HTMLResponse  # noqa: PLC0415

    nest = request.app.state.nest
    job = changes.read(nest)
    if (
        job
        and job["state"] in ("done", "failed", "interrupted")
        and (job["settled"] or job["state"] != "done")
    ):
        return HTMLResponse("", headers={"HX-Refresh": "true"})  # the whole page, anew
    return render(request, "admin/_change.html", change=job)


@router.post("/modules/update-all")
async def update_all(request: Request, user: CurrentUser = Depends(admin_only)):
    """Every module the registry has newer, to its newest, as one change."""
    from nest.versions import updates  # noqa: PLC0415

    offers, _problems = _offers(request, fresh=True)
    newer = updates(list(_versions(request, offers).values()))
    if not newer:
        return _page(
            request, tab="updates", steps=[translator(request)("Everything is up to date.")]
        )
    return await _versions_change(request, {r.name: r.latest for r in newer}, user, "updates")


@router.post("/modules/add")
async def add(request: Request, user: CurrentUser = Depends(admin_only)):
    """A module from the registry: installed (its newest, with the Nest packages it needs
    that the site lacks), then enabled at an address."""
    t = translator(request)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    route = str(form.get("route", "")).strip()
    if route and not route.startswith("/"):
        route = "/" + route
    offers, problems = _offers(request, fresh=True)
    offer = offers.get(name)
    if offer is None:
        return _page(
            request,
            tab="registry",
            problems=problems or [t("{name} is not in the registry.", name=name)],
            status_code=400,
        )
    have = set(_versions(request, offers)) | {
        r.name for r in status(_app_dir(request.app.state.nest), request.app.state.nest.environ)
    }
    wanted = {name: offer.version}
    for dep in offer.deps:  # the Nest packages it needs that the site does not have
        if dep not in have and dep in offers:
            wanted[dep] = offers[dep].version
    ok, said = await run_in_threadpool(
        _run_nest, request, ["version", *[f"{n}={v}" for n, v in wanted.items()]], user.email
    )
    if not ok:
        return _page(request, tab="registry", problems=said, status_code=400)
    done = [s for s in said if "→" in s]
    if offer.type in ("module", "subsystem", "content"):
        args = ["enable", name, *(["--route", route] if route else [])]
        ok, said = await run_in_threadpool(_run_nest, request, args, user.email)
        if not ok:
            return _page(
                request,
                tab="installed",
                problems=[t("{name} is installed; enabling it failed:", name=name), *said],
                status_code=400,
            )
        done.append(t("{name} is enabled.", name=name))
    return _after(request, done, "installed", place=name)


# --- a module's own page: its versions, its migrations ------------------------------------------


def _older(version: str, mine: Any) -> bool:
    from nest.versions import _vkey  # noqa: PLC0415

    return mine is not None and _vkey(version) < _vkey(mine.running)


def _module(request: Request, name: str, *, steps=None, problems=None, status_code=200) -> Any:
    from nest import versions  # noqa: PLC0415
    from nest.remote import RemoteError, package  # noqa: PLC0415
    from nest.resolve import _core_version  # noqa: PLC0415

    nest = request.app.state.nest
    row = next((r for r in status(_app_dir(nest), nest.environ) if r.name == name), None)
    offers, _p = _offers(request)
    mine = _versions(request, offers).get(name)
    if row is None and mine is None:
        raise HTTPException(404)
    releases, registry_problems = [], []
    try:
        detail = package(name, None, nest.environ)
        core = _core_version()
        from packaging.specifiers import SpecifierSet  # noqa: PLC0415

        for r in reversed(detail.get("releases", [])):
            fits = (
                not core
                or not r.get("nest")
                or SpecifierSet(r["nest"]).contains(core, prereleases=True)
            )
            releases.append({**r, "fits": fits, "older": _older(r.get("version", ""), mine)})
    except RemoteError as e:
        missing = any("Not Found" in p or "404" in p for p in e.problems)
        registry_problems = [] if missing else e.problems
    except Exception as e:  # noqa: BLE001
        registry_problems = [str(e)]
    return render(
        request,
        "admin/module.html",
        fragment="page" if is_htmx(request) else None,
        status_code=status_code,
        row=row,
        mine=mine,
        releases=releases,
        registry_problems=registry_problems,
        migrations=versions.migrations(nest, name) if nest.plan.unit(name) else None,
        **_placing(request, name),
        steps=steps or [],
        problems=problems or [],
        change=changes.read(nest),
        back=f"{nest.admin_root}/modules/{name}",
    )


def _placing(request: Request, name: str) -> dict[str, Any]:
    """What the module offers the site to reach it without code (offers: in its
    manifest), and where it can go: the site's menus, the theme's regions."""
    from nest import regions  # noqa: PLC0415

    nest = request.app.state.nest
    unit = nest.plan.unit(name)
    if unit is None:
        return {"offers": None}
    offers = unit.entry.manifest.offers
    base = nest.module_url(name)
    link = None
    if offers.menu is not None and base:
        path = offers.menu.path.lstrip("/")
        link = base.rstrip("/") + "/" + path if path else base.rstrip("/") + "/"
    return {
        "offers": offers,
        "link": link,
        "menus": nest.lookup("content.menus", None) or [],
        "theme_regions": regions.theme_regions(nest),
    }


@router.post("/modules/{name}/place-menu")
async def place_menu(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    """A link to the module's pages, at the end of a menu of the site."""
    t = translator(request)
    form = await request.form()
    placing = _placing(request, name)
    if not placing.get("link"):
        raise HTTPException(404)
    made = request.app.state.nest.lookup(
        "content.menu.link",
        {
            "menu": str(form.get("menu", "")),
            "title": str(form.get("title", "")).strip(),
            "url": placing["link"],
        },
    )
    if not made:
        return _module(
            request,
            name,
            problems=[t("The link was not added: choose a menu and give it a label.")],
            status_code=400,
        )
    return _module(
        request, name, steps=[t("A link to it is in the menu {menu}.", menu=made["menu"])]
    )


@router.get("/modules/{name}")
def module_page(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    return _module(request, name)


@router.post("/modules/{name}/version")
async def module_version(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    """Another version of a module (newer or older), or the image's again ("image")."""
    form = await request.form()
    version = str(form.get("version", "")).strip()
    if not version:
        raise HTTPException(400)
    if not _start(request, ["version", f"{name}={version}"], user, name=name):
        return _module(request, name, problems=[_busy(request)], status_code=409)
    return _module(request, name)


@router.post("/modules/{name}/migrate")
async def module_migrate(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    """A module's migrations up or down to a revision (head, base), after a backup."""
    form = await request.form()
    target = str(form.get("target", "")).strip()
    if not target:
        raise HTTPException(400)
    ok, said = await run_in_threadpool(_run_nest, request, ["migrate", name, target], user.email)
    if not ok:
        return _module(request, name, problems=said, status_code=400)
    return _module(
        request, name, steps=[s for s in said if s.startswith(("✓", name, "backup"))] or said
    )


# --- enable, disable, uninstall ------------------------------------------------------------------


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
