"""The panel's languages page: which languages the site is in, and which is its default.

The manifest gives the starting set (``application.languages``); what an administrator
chooses here is kept in the workspace (nest.composition) and applied by making the site
again (nest serve's workers reloaded, or in place under nest run). With addresses per
language (``language_urls: prefix``) the default is at / and every other language under
its prefix (/en/...). Adding a language changes no table: what is translated into it is
rows, in the modules that keep their text per language.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from nest_auth import CurrentUser, require_role

from nest import render, toast, translator
from nest.composition import load_languages, save
from nest.i18n import LANGUAGE_NAMES as NAMES
from nest.modules import reload_app

router = APIRouter()
admin_only = require_role("admin")
_CODE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")


def _current(nest: Any) -> tuple[list[str], str]:
    site, default = load_languages(nest.workspace)
    if site:
        return site, default or site[0]
    return list(nest.site_languages), nest.catalogs.default


def _page(request: Request, problems: list[str] | None = None, status_code: int = 200) -> Any:
    nest = request.app.state.nest
    site, default = _current(nest)
    running = list(nest.site_languages)
    application = nest.manifest.application
    return render(
        request,
        "admin/languages.html",
        site=site,
        default=default,
        names=NAMES,
        translated=set(nest.catalogs.languages),
        pending=site != running or default != nest.catalogs.default,
        prefix=bool(application and application.language_urls == "prefix"),
        problems=problems or [],
        status_code=status_code,
    )


@router.get("/languages")
def languages_page(request: Request, user: CurrentUser = Depends(admin_only)):
    return _page(request)


@router.post("/languages")
def languages_change(
    request: Request,
    action: str = Form(""),
    code: str = Form(""),
    user: CurrentUser = Depends(admin_only),
):
    nest = request.app.state.nest
    t = translator(request)
    site, default = _current(nest)
    code = code.strip().lower()
    if action == "add":
        if not _CODE.match(code):
            return _page(
                request,
                [t("'{code}' is not a language code (ro, en, hu, pt-br...)", code=code)],
                400,
            )
        if code in site:
            return _page(request, [t("{code} is a language of the site already.", code=code)], 400)
        site = [*site, code]
    elif action == "remove":
        if code == default:
            return _page(
                request,
                [t("The default language cannot be removed; make another the default first.")],
                400,
            )
        site = [x for x in site if x != code]
    elif action == "default":
        if code not in site:
            return _page(request, [t("{code} is not a language of the site.", code=code)], 400)
        default = code
    else:
        return _page(request, [t("Nothing to do.")], 400)
    save(nest.workspace, languages=(site, default))
    toast(request, t("The languages are saved."))
    if reload_app(nest):
        toast(request, t("The site is reloading to apply it."))
    else:
        toast(request, t("It applies when the site is restarted."), "warning")
    return _page(request)
