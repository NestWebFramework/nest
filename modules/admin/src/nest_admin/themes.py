"""The panel's themes page: the application's look, chosen among the installed themes.

Each theme is shown as a card in its own colours. An administrator may **preview** one:
the site is then shown to them alone in that theme (a signed cookie, an hour at most;
everyone else sees the theme in use), with a bar to stop; the admin panel itself keeps
the theme in use, so a theme can never lock the way back. **Use** makes it the site's
theme: it is tried first (nest.themes: the pages rendered with it), kept in the
workspace, and the running site reloaded.
"""

from __future__ import annotations

import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from nest import render, toast, translator
from nest.modules import history, reload_app
from nest.themes import ThemeError, themes, use

router = APIRouter()
admin_only = require_role("admin")
COOKIE = "nest_theme_preview"
PREVIEW_SECONDS = 3600


def _app_dir(nest: Any) -> Path:
    return Path(nest.plan.app.manifest.root)


def _page(request: Request, *, steps=None, problems=None, status_code: int = 200) -> Any:
    nest = request.app.state.nest
    rows = themes(_app_dir(nest), nest.environ)
    running = nest.plan.theme.name if nest.plan.theme is not None else None
    log = [e for e in history(nest.workspace, 40) if e.get("theme")][:10]
    # where each theme's settings are: its own, else those of the theme it is built on
    owners = {owner for _key, owner, _name, spec in nest.settings.specs() if spec.editable}
    extends = {t.name: t.extends for t in rows}
    settings_of = {}
    for t in rows:
        name, seen = t.name, set()
        while name and name not in owners and name not in seen:
            seen.add(name)
            name = extends.get(name)
        if name in owners:
            settings_of[t.name] = name
    return render(
        request,
        "admin/themes.html",
        rows=rows,
        settings_of=settings_of,
        running=running,
        steps=steps or [],
        problems=problems or [],
        log=log,
        status_code=status_code,
    )


@router.get("/themes")
def themes_page(request: Request, user: CurrentUser = Depends(admin_only)):
    return _page(request)


@router.post("/themes/{name}/use")
async def themes_use(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    nest = request.app.state.nest
    t = translator(request)
    try:
        await run_in_threadpool(
            lambda: use(_app_dir(nest), name, dict(nest.environ), who=user.email, reload=False)
        )
    except ThemeError as e:
        return _page(request, problems=e.problems, status_code=400)
    steps = [t("{name} is the site's theme now.", name=name)]
    steps.append(
        t("The site is reloading to apply it.")
        if reload_app(nest)
        else t("It applies when the site is restarted.")
    )
    toast(request, steps[0])
    response = _page(request, steps=steps)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/themes/preview/stop")
def themes_preview_stop(request: Request):
    nest = request.app.state.nest
    response = RedirectResponse(f"{nest.admin_root}/themes", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/themes/{name}/preview")
def themes_preview(request: Request, name: str, user: CurrentUser = Depends(admin_only)):
    nest = request.app.state.nest
    if name not in {r.name for r in themes(_app_dir(nest), nest.environ)}:
        raise HTTPException(404)
    sign = nest.module_state["admin"]["sign"]
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE,
        sign(f"{name}|{int(time.time()) + PREVIEW_SECONDS}"),
        max_age=PREVIEW_SECONDS,
        httponly=True,
        samesite="lax",
        secure=nest.production,
        path="/",
    )
    return response


class ThemePreview:
    """Shows the site in a previewed theme to the administrator who asked (their signed
    cookie): an application made with that theme, without starting it (no worlds, no
    background tasks), kept while it is wanted. The admin panel is never previewed."""

    def __init__(self, app: ASGIApp, *, unsign: Any):
        self.app, self.unsign = app, unsign
        self.previews: dict[str, tuple[float, Any]] = {}

    def _theme(self, scope: Scope) -> str | None:
        for key, value in scope.get("headers", []):
            if key == b"cookie":
                jar = SimpleCookie()
                try:
                    jar.load(value.decode("latin-1"))
                except Exception:  # noqa: BLE001 - a malformed cookie is no cookie
                    continue
                if COOKIE in jar:
                    found = self.unsign(jar[COOKIE].value)
                    if found and "|" in found:
                        name, _, until = found.partition("|")
                        if until.isdigit() and int(until) > time.time():
                            return name
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        theme = self._theme(scope)
        nest = scope["app"].state.nest
        admin = nest.admin_root or ""
        path = scope["path"]
        if (
            theme is None
            or (nest.plan.theme is not None and theme == nest.plan.theme.name)
            or (nest.admin_root is not None and (path == admin or path.startswith(admin + "/")))
            or path.startswith("/_nest/events")
        ):
            await self.app(scope, receive, send)
            return
        preview = await self._preview(nest, theme)
        if preview is None:
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})["theme_preview"] = theme
        await preview(scope, receive, send)

    async def _preview(self, nest: Any, theme: str) -> Any:
        from nest import composition  # noqa: PLC0415
        from nest.host import close_providers, create_app  # noqa: PLC0415

        file = composition.path(nest.workspace)
        stamp = file.stat().st_mtime if file.exists() else 0.0
        kept = self.previews.get(theme)
        if kept is not None and kept[0] == stamp:
            return kept[1]
        env = {**nest.environ, "NEST_MIGRATE": "off", "NEST_ROLE": "web"}
        env.pop("NEST_ENGINE_URL", None)
        try:
            app = await run_in_threadpool(
                lambda: create_app(Path(nest.plan.app.manifest.root), environ=env, theme=theme)
            )
        except Exception:  # noqa: BLE001 - the site as it is, rather than an error
            return None
        for _stamp, old in self.previews.values():  # one preview kept at a time
            close_providers(old.state.nest)
        self.previews = {theme: (stamp, app)}
        return app
