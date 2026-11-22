"""The panel's settings page: every module's settings, changed on the running application.

Each module declares its settings in its manifest (typed, with a label and a
description); this page shows the ones marked editable, a section per module, and
saves them in the application's settings store (its workspace), where they win over
the manifest's values. A value the environment sets is shown and cannot be changed
here; a secret is set here (kept encrypted), never shown again: left empty it stays. A module may judge its values before they are saved
(``host.check_settings``). Administrators reach every section; a module may let another
role change its own (admin: settings_role:, a game's masters its rules).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role, require_user

from nest import render, toast, translator
from nest.modules import reload_app
from nest.settings import SettingsError

router = APIRouter()
admin_only = require_role("admin")


THEMES = "themes"  # the tab that holds every theme's settings, a tab each under it


def settings_roles(nest: Any) -> dict[str, str]:
    """Who may change each module's settings besides administrators (its manifest's admin:
    settings_role:, a game's masters its rules), by module; a page in the panel or not."""
    out = {}
    for u in nest.plan.units:
        role = ((u.entry.manifest.raw or {}).get("admin") or {}).get("settings_role")
        if role:
            out[u.name] = str(role)
    return out


def may_change(request: Request, user: Any, owner: str) -> bool:
    """An administrator may change every module's settings; another, those of the modules
    that let its role (admin: settings_role:)."""
    if user.has("admin"):
        return True
    role = settings_roles(request.app.state.nest).get(owner)
    return bool(role) and user.has(role)


def _sections(request: Request, user: Any = None) -> list[dict[str, Any]]:
    """Every package's settings, a section each: the modules' in the plan's order, then the
    installed themes' (``theme``: True), the one in use and those it is built on first."""
    nest = request.app.state.nest
    themes = getattr(nest, "installed_themes", {})
    chain = [t.name for t in nest.plan.themes]
    titles = {u.name: (u.entry.manifest.module.title or u.name) for u in nest.plan.units}
    titles.update(themes)
    order = [u.name for u in nest.plan.units if u.name not in themes]
    order += chain + sorted(n for n in themes if n not in chain)
    sections: dict[str, dict[str, Any]] = {}
    for key, owner, name, spec in nest.settings.specs():
        if not spec.editable or owner not in titles:
            continue
        if user is not None and not may_change(request, user, owner):
            continue
        source = nest.settings.source(key)
        section = sections.setdefault(
            owner,
            {
                "owner": owner,
                "title": titles[owner],
                "items": [],
                "theme": owner in themes,
                "in_use": owner in chain,
            },
        )
        section["items"].append(
            {
                "key": key,
                "name": name,
                "spec": spec,
                "value": None if spec.secret else nest.settings.get(key),
                "source": source,
                "locked": source == "environment",
                "is_set": bool(nest.settings.get(key)) if spec.secret else None,
            }
        )
    return sorted(sections.values(), key=lambda s: order.index(s["owner"]))


@router.get("/settings")
def settings_home(request: Request, user: CurrentUser = Depends(require_user)):
    """The first section's tab (of those this user may change)."""
    sections = _sections(request, user)
    if not user.has("admin") and not sections:
        raise HTTPException(403)
    nest = request.app.state.nest
    if not sections:
        return render(request, "admin/settings.html", **_tabs(sections, None), errors={})
    first = next((s for s in sections if not s["theme"]), sections[0])
    return RedirectResponse(f"{nest.admin_root}/settings/{first['owner']}", status_code=303)


def _tabs(sections: list[dict[str, Any]], current: dict[str, Any] | None) -> dict[str, Any]:
    """The tabs: a module's section each, and one for the themes, whose own tabs are under
    it when it is open (the theme in use first)."""
    return {
        "sections": [s for s in sections if not s["theme"]],
        "themes": [s for s in sections if s["theme"]],
        "current": current,
    }


@router.get("/settings/themes")
def settings_themes(request: Request, user: CurrentUser = Depends(admin_only)):
    """The themes' tab: the theme in use's settings (or the first theme's that has any)."""
    themes = [s for s in _sections(request) if s["theme"]]
    if not themes:
        raise HTTPException(404)
    return RedirectResponse(
        f"{request.app.state.nest.admin_root}/settings/{themes[0]['owner']}", status_code=303
    )


@router.get("/settings/{owner}")
def settings_page(request: Request, owner: str, user: CurrentUser = Depends(require_user)):
    """One module's (or theme's) settings, the others (those this user may change) a tab
    away."""
    if not may_change(request, user, owner):
        raise HTTPException(403)
    sections = _sections(request, user)
    current = next((s for s in sections if s["owner"] == owner), None)
    if current is None:
        raise HTTPException(404)
    return render(request, "admin/settings.html", **_tabs(sections, current), errors={})


@router.post("/settings/{owner}")
async def save_settings(request: Request, owner: str, user: CurrentUser = Depends(require_user)):
    nest = request.app.state.nest
    t = translator(request)
    if not may_change(request, user, owner):
        raise HTTPException(403)
    section = next((s for s in _sections(request, user) if s["owner"] == owner), None)
    if section is None:
        raise HTTPException(404)
    form = await request.form()
    wanted: dict[str, Any] = {}
    reset: list[str] = []
    for item in section["items"]:
        if item["locked"]:
            continue
        key, spec = item["key"], item["spec"]
        if form.get(f"reset:{key}"):
            reset.append(key)
            continue
        if spec.type == "bool":
            wanted[key] = bool(form.get(key))
        elif spec.secret:  # never shown: left empty keeps it, typed replaces it
            typed = str(form.get(key, "")).strip()
            if typed:
                wanted[key] = typed
        else:
            wanted[key] = str(form.get(key, "")).strip()
    problems: list[str] = []
    check = nest.settings_checks.get(owner)
    if check is not None:
        values = {i["name"]: i["value"] for i in section["items"]}
        values.update({k.split(".", 1)[1]: v for k, v in wanted.items()})
        for k in reset:
            values[k.split(".", 1)[1]] = None  # back to its default; the module knows it
        for p in check(values) or []:  # a message, or (message, params), in English
            message, params = (p, {}) if isinstance(p, str) else p
            problems.append(t(message, **params))
    changed: list[str] = []
    if not problems:
        try:
            for key in reset:
                nest.settings.reset(key)
                changed.append(key)
            for key, value in wanted.items():
                if value != nest.settings.get(key):
                    nest.settings.set(key, value)
                    changed.append(key)
        except SettingsError as e:
            problems = [str(e)]
    if problems:
        for p in problems:
            toast(request, p, "error")
        sections = _sections(request, user)
        return render(
            request,
            "admin/settings.html",
            **_tabs(sections, next(s for s in sections if s["owner"] == owner)),
            errors={owner: problems},
            status_code=400,
        )
    toast(request, t("Settings saved: {section}.", section=t(section["title"])))
    specs = {key: spec for key, _o, _n, spec in nest.settings.specs()}
    if any(specs[k].restart for k in changed if k in specs):  # its routes depend on it
        if reload_app(nest):
            toast(request, t("The site is reloading to apply it."))
        else:
            toast(request, t("It applies when the site is restarted."), "warning")
    return RedirectResponse(f"{nest.admin_root}/settings/{owner}", status_code=303)
