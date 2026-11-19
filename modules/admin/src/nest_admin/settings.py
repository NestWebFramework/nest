"""The panel's settings page: every module's settings, changed on the running application.

Each module declares its settings in its manifest (typed, with a label and a
description); this page shows the ones marked editable, a section per module, and
saves them in the application's settings store (its workspace), where they win over
the manifest's values. A value the environment sets is shown and cannot be changed
here; a secret is never shown. A module may judge its values before they are saved
(``host.check_settings``). Only administrators reach it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role

from nest import render, toast, translator
from nest.modules import reload_running
from nest.settings import SettingsError

router = APIRouter()
admin_only = require_role("admin")


def _sections(request: Request) -> list[dict[str, Any]]:
    nest = request.app.state.nest
    titles = {u.name: (u.entry.manifest.module.title or u.name) for u in nest.plan.units}
    order = [u.name for u in nest.plan.units]
    sections: dict[str, dict[str, Any]] = {}
    for key, owner, name, spec in nest.settings.specs():
        if not spec.editable or owner not in titles:
            continue
        source = nest.settings.source(key)
        section = sections.setdefault(owner, {"owner": owner, "title": titles[owner], "items": []})
        section["items"].append(
            {
                "key": key,
                "name": name,
                "spec": spec,
                "value": None if spec.secret else nest.settings.get(key),
                "source": source,
                "locked": spec.secret or source == "environment",
            }
        )
    return sorted(sections.values(), key=lambda s: order.index(s["owner"]))


@router.get("/settings")
def settings_home(request: Request, user: CurrentUser = Depends(admin_only)):
    """The first section's tab."""
    sections = _sections(request)
    nest = request.app.state.nest
    if not sections:
        return render(request, "admin/settings.html", sections=[], current=None, errors={})
    return RedirectResponse(f"{nest.admin_root}/settings/{sections[0]['owner']}", status_code=303)


@router.get("/settings/{owner}")
def settings_page(request: Request, owner: str, user: CurrentUser = Depends(admin_only)):
    """One module's settings, the others a tab away."""
    sections = _sections(request)
    current = next((s for s in sections if s["owner"] == owner), None)
    if current is None:
        raise HTTPException(404)
    return render(request, "admin/settings.html", sections=sections, current=current, errors={})


@router.post("/settings/{owner}")
async def save_settings(request: Request, owner: str, user: CurrentUser = Depends(admin_only)):
    nest = request.app.state.nest
    t = translator(request)
    section = next((s for s in _sections(request) if s["owner"] == owner), None)
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
        sections = _sections(request)
        return render(
            request,
            "admin/settings.html",
            sections=sections,
            current=next(s for s in sections if s["owner"] == owner),
            errors={owner: problems},
            status_code=400,
        )
    toast(request, t("Settings saved: {section}.", section=t(section["title"])))
    specs = {key: spec for key, _o, _n, spec in nest.settings.specs()}
    if any(specs[k].restart for k in changed if k in specs):  # its routes depend on it
        if reload_running(nest.workspace):
            toast(request, t("The site is reloading to apply it."))
        else:
            toast(request, t("It applies when the site is restarted."), "warning")
    return RedirectResponse(f"{nest.admin_root}/settings/{owner}", status_code=303)
