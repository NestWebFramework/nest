"""The keeper: Nest's own orchestration of its applications.

What is generic to every application lives here: which applications exist
(installed packages of type application, and the folders of the ``apps``
setting), how each is planned (start order, routes, bindings, notes), what is
wrong with it, whether it answers on its port, and the packages Nest can see.
What is specific to one application is in that application's admin panel.
The pages are the keeper's admin panel's (the admin role).
"""

from __future__ import annotations

import asyncio
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from nest_db import Database

from nest import ModuleHost, admin_url, bound, render
from nest.catalog import Catalog, Entry
from nest.contract import load_contracts
from nest.host import module_state
from nest.manifest import MANIFEST_FILE, ManifestError, load_manifest
from nest.resolve import PlanError, plan
from nest_keeper import tokens

__all__ = ["applications", "probed"]

admin = APIRouter()
router = APIRouter()
keeper = require_role("admin")
PROBE_SECONDS = 0.3


@dataclass
class Application:
    name: str
    root: Path
    source: str  # "package" or the folder it was found in
    title: str = ""
    version: str = ""
    port: int | None = None
    units: list[dict[str, Any]] = field(default_factory=list)
    bindings: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    running: bool | None = None  # None: not asked yet


def applications(folders: list[Path]) -> list[Application]:
    """Every application Nest can see, each planned as ``nest plan`` would."""
    contract = load_contracts()
    found: dict[str, Application] = {}
    roots: list[tuple[Path, str]] = []
    for entry in Catalog.discover().of_type("application"):
        roots.append((entry.root, "package"))
    for folder in folders:
        if (
            folder / MANIFEST_FILE
        ).is_file():  # a folder that is an application (a repo of its own)
            roots.append((folder, str(folder)))
        elif folder.is_dir():
            for path in sorted(folder.glob(f"*/{MANIFEST_FILE}")):
                roots.append((path.parent, str(folder)))
    for root, source in roots:
        try:
            manifest = load_manifest(root)
        except ManifestError as e:
            found.setdefault(root.name, Application(root.name, root, source, problems=[str(e)]))
            continue
        if manifest.type != "application" or manifest.name in found:
            continue
        app = Application(
            manifest.name,
            root,
            source,
            title=(manifest.application.title if manifest.application else "") or manifest.name,
            version=manifest.module.version,
            port=manifest.application.port if manifest.application else None,
            problems=list(contract.validate(manifest)),
        )
        try:
            the_plan = plan(
                Entry(manifest=manifest, source="application"), Catalog.discover(root), contract
            )
        except PlanError as e:
            app.problems.append(str(e))
        else:
            app.units = [
                {
                    "name": u.name,
                    "type": u.entry.type,
                    "version": u.entry.manifest.module.version,
                    "route": (u.instance.route if u.instance else None) or "",
                }
                for u in the_plan.units
            ]
            app.bindings = {k: list(b.providers) for k, b in the_plan.bindings.items()}
            app.notes = list(the_plan.notes)
        found[manifest.name] = app
    return sorted(found.values(), key=lambda a: a.name)


def _probe(port: int) -> bool:
    """Whether something answers /healthz on this machine's port (and only there)."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{int(port)}/healthz", timeout=PROBE_SECONDS
        ) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


async def probed(apps: list[Application]) -> list[Application]:
    async def one(app: Application) -> None:
        app.running = await asyncio.to_thread(_probe, app.port) if app.port else None

    await asyncio.gather(*(one(a) for a in apps))
    return apps


def _folders(request: Request) -> list[Path]:
    return module_state(request, "keeper")["folders"]


@admin.get("/")
async def index(request: Request, user: CurrentUser = Depends(keeper)):
    apps = await probed(await asyncio.to_thread(applications, _folders(request)))
    return render(
        request,
        "keeper/index.html",
        fragment="apps",
        apps=apps,
        base=admin_url(request, "keeper"),
        here=request.app.state.nest.name,
    )


@admin.get("/packages")
def packages(request: Request, user: CurrentUser = Depends(keeper)):
    catalog = Catalog.discover()
    by_type: dict[str, list[Entry]] = {}
    for entry in catalog:
        by_type.setdefault(entry.type, []).append(entry)
    return render(
        request,
        "keeper/packages.html",
        by_type=dict(sorted(by_type.items())),
        problems=catalog.problems,
        base=admin_url(request, "keeper"),
    )


@admin.get("/app/{name}")
async def detail(request: Request, name: str, user: CurrentUser = Depends(keeper)):
    apps = {a.name: a for a in await asyncio.to_thread(applications, _folders(request))}
    if name not in apps:
        raise HTTPException(404)
    (app,) = await probed([apps[name]])
    return render(request, "keeper/app.html", app=app, base=admin_url(request, "keeper"))


def _app_or_404(request: Request, name: str) -> Application:
    apps = {a.name: a for a in applications(_folders(request))}
    if name not in apps:
        raise HTTPException(404)
    return apps[name]


def _packages_page(
    request: Request, app: Application, *, steps=None, problems=None, status_code=200
):
    from nest.packages import PackageError, status  # noqa: PLC0415

    rows, trouble = [], list(problems or [])
    managed = (app.root / "pyproject.toml").is_file()
    if managed:
        try:
            rows = status(app.root)
        except PackageError as e:
            trouble += e.problems
    present = {r.offer.name for r in rows if r.installed}
    rows = [
        r for r in rows if not r.offer.part_of or r.offer.part_of in present
    ]  # a game's parts with its engine
    groups = {
        "used": [r for r in rows if r.used],
        "installed": [r for r in rows if r.installed and r.direct and not r.used],
        "with": [r for r in rows if r.installed and not r.direct and not r.used],
        "available": [r for r in rows if not r.installed],
    }
    return render(
        request,
        "keeper/app_packages.html",
        app=app,
        managed=managed,
        groups=groups,
        steps=steps or [],
        problems=trouble,
        base=admin_url(request, "keeper"),
        status_code=status_code,
    )


@admin.get("/app/{name}/packages")
async def app_packages(request: Request, name: str, user: CurrentUser = Depends(keeper)):
    app = await asyncio.to_thread(_app_or_404, request, name)
    return await asyncio.to_thread(_packages_page, request, app)


@admin.post("/app/{name}/packages/{package}/{action}")
async def app_package_change(
    request: Request, name: str, package: str, action: str, user: CurrentUser = Depends(keeper)
):
    """Install a package of this server's registry into the application, or remove it:
    its pyproject.toml and module.yml, then uv sync (nest.packages)."""
    from nest.packages import PackageError, add, remove  # noqa: PLC0415

    if action not in ("add", "remove"):
        raise HTTPException(404)
    app = await asyncio.to_thread(_app_or_404, request, name)
    steps: list[str] = []
    try:
        await asyncio.to_thread(
            (add if action == "add" else remove), app.root, package, say=steps.append
        )
    except PackageError as e:
        return await asyncio.to_thread(
            _packages_page, request, app, problems=e.problems, status_code=400
        )
    return await asyncio.to_thread(_packages_page, request, app, steps=steps)


@admin.get("/tokens")
def token_list(
    request: Request, user: CurrentUser = Depends(keeper), db: Database = bound(Database)
):
    return render(
        request,
        "keeper/tokens.html",
        tokens=tokens.listing(db),
        secret=None,
        error=None,
        base=admin_url(request, "keeper"),
    )


@admin.post("/tokens")
def token_create(
    request: Request,
    name: str = Form(""),
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    try:
        secret, _t = tokens.create(db, name)
    except ValueError as e:
        return render(
            request,
            "keeper/tokens.html",
            status_code=400,
            tokens=tokens.listing(db),
            secret=None,
            error=str(e),
            base=admin_url(request, "keeper"),
        )
    # Shown this once, on this answer (never stored, never in an address or a log).
    return render(
        request,
        "keeper/tokens.html",
        tokens=tokens.listing(db),
        secret=secret,
        error=None,
        base=admin_url(request, "keeper"),
    )


@admin.post("/tokens/{token_id:int}/revoke")
def token_revoke(
    request: Request,
    token_id: int,
    user: CurrentUser = Depends(keeper),
    db: Database = bound(Database),
):
    if not tokens.revoke(db, token_id):
        raise HTTPException(404)
    return RedirectResponse(admin_url(request, "keeper", "tokens"), status_code=303)


@router.get("/")
def front(request: Request):
    return RedirectResponse(admin_url(request, "keeper") + "/", status_code=303)


def setup(host: ModuleHost) -> None:
    raw = str(host.settings.get("apps") or "")
    host.state["folders"] = [
        Path(os.path.expanduser(p.strip())).resolve() for p in raw.split(",") if p.strip()
    ]
    host.admin(admin)
    if host.route is not None:
        host.mount(router)
        host.mount(api)  # the REST API, at <route>/api/v1


from nest_keeper.rest import api  # noqa: E402 - after applications and probed, which it uses
