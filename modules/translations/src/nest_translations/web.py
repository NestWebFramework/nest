"""The translations admin page: what is left to translate, per kind and language; an
editor beside the original; export and import (JSON) for translating elsewhere."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, require_role

from nest import language_name, render, toast, translator
from nest_translations import service
from nest_translations.kinds import Kind, TranslationsError

admin = APIRouter()
editor = require_role("editor")
PAGE = 50


def _state(request: Request) -> dict[str, Any]:
    return request.app.state.nest.module_state["translations"]


def _languages(request: Request) -> tuple[list[str], str]:
    nest = request.app.state.nest
    return list(nest.site_languages), nest.catalogs.default


def _kind(request: Request, subject: str) -> Kind:
    kind = _state(request)["kinds"].get(subject)
    if kind is None:
        raise HTTPException(404)
    return kind


def _base(request: Request) -> str:
    return f"{request.app.state.nest.admin_root}/translations"


def _message(request: Request, e: TranslationsError) -> str:
    return translator(request)(e.message, **e.params)


@admin.get("/")
def overview(
    request: Request,
    subject: str = "",
    lang: str = "",
    state: str = "todo",
    page: int = 1,
    user: CurrentUser = Depends(editor),
):
    kinds: dict[str, Kind] = _state(request)["kinds"]
    db = _state(request)["db"]
    site, default = _languages(request)
    targets = [x for x in site if x != default]
    names = {x: language_name(x) for x in site}
    if not kinds or not targets:
        return render(
            request,
            "translations/overview.html",
            kinds=kinds,
            targets=targets,
            names=names,
            default=default,
        )
    kind = kinds.get(subject) or next(iter(kinds.values()))
    lang = lang if lang in targets else targets[0]
    state = state if state in (*service.STATES, "todo", "all") else "todo"
    stand = service.states(db, kind, site, default)
    tally = {
        k.subject: service.counts(service.states(db, k, site, default), lang)
        for k in kinds.values()
    }
    wanted = service.TODO if state == "todo" else service.STATES if state == "all" else (state,)
    ids = sorted((i for i, by in stand.items() if by.get(lang) in wanted), reverse=True)
    page = max(page, 1)
    shown = ids[(page - 1) * PAGE : page * PAGE]
    names_of = service.titles(db, kind, shown, default) if shown else {}
    rows = [
        {
            "id": i,
            "title": names_of.get(i, f"#{i}"),
            "states": stand[i],
            "edit": kind.edit_url(request.app.state.nest.admin_root, i),
        }
        for i in shown
    ]
    return render(
        request,
        "translations/overview.html",
        kinds=kinds,
        kind=kind,
        targets=targets,
        names=names,
        default=default,
        lang=lang,
        state=state,
        counts=tally[kind.subject],
        tally=tally,
        rows=rows,
        total=len(ids),
        page=page,
        pages=max(1, -(-len(ids) // PAGE)),
        base=_base(request),
    )


def _editor(
    request: Request, kind: Kind, owner_id: Any, lang: str, form: Any = None, status_code: int = 200
) -> Any:
    db = _state(request)["db"]
    site, default = _languages(request)
    rows = service.texts(db, kind, owner_id)
    source = rows.get(default)
    if source is None:
        raise HTTPException(404)
    return render(
        request,
        "translations/edit.html",
        kind=kind,
        owner_id=owner_id,
        lang=lang,
        default=default,
        names={x: language_name(x) for x in site},
        targets=[x for x in site if x != default],
        source=source,
        form=form,
        edit=kind.edit_url(request.app.state.nest.admin_root, owner_id),
        base=_base(request),
        status_code=status_code,
    )


def _owner(kind: Kind, raw: str) -> Any:
    column = kind.model.__table__.columns["owner_id"]
    try:
        return column.type.python_type(raw)
    except (ValueError, NotImplementedError):
        return raw


@admin.get("/{subject}/{owner_id}")
def edit(
    request: Request,
    subject: str,
    owner_id: str,
    lang: str = "",
    user: CurrentUser = Depends(editor),
):
    kind = _kind(request, subject)
    site, default = _languages(request)
    targets = [x for x in site if x != default]
    if not targets:
        raise HTTPException(404)
    return _editor(request, kind, _owner(kind, owner_id), lang if lang in targets else targets[0])


@admin.post("/{subject}/{owner_id}")
async def edit_save(
    request: Request, subject: str, owner_id: str, user: CurrentUser = Depends(editor)
):
    kind = _kind(request, subject)
    owner = _owner(kind, owner_id)
    site, default = _languages(request)
    form = await request.form()
    lang = str(form.get("lang") or "")
    if lang == default or lang not in site:
        raise HTTPException(400)
    if form.get("copy"):  # start from the original: shown, not saved
        source = service.texts(_state(request)["db"], kind, owner).get(default)
        filled = {f"tr_{lang}_{f}": getattr(source, f) for f in kind.fields} if source else {}
        filled |= {f"tr_{lang}_present": "1", f"tr_{lang}_status": "draft"}
        return _editor(request, kind, owner, lang, form=filled)
    try:
        changed = service.save_form(_state(request)["db"], kind, owner, form, site, default)
        _state(request)["announce"](kind.subject, [owner], changed)
    except TranslationsError as e:
        toast(request, _message(request, e), "error")
        return _editor(request, kind, owner, lang, form=form, status_code=400)
    toast(request, translator(request)("Saved."))
    back = str(form.get("next") or "")
    target = (
        back
        if back.startswith(_base(request))
        else f"{_base(request)}/{subject}/{owner_id}?lang={lang}"
    )
    return RedirectResponse(target, status_code=303)


@admin.get("/export")
def export(
    request: Request,
    lang: str = "",
    subject: str = "",
    only: str = "todo",
    user: CurrentUser = Depends(editor),
):
    kinds: dict[str, Kind] = _state(request)["kinds"]
    site, default = _languages(request)
    chosen = [kinds[subject]] if subject in kinds else list(kinds.values())
    try:
        data = service.export(_state(request)["db"], chosen, lang, site, default, only)
    except TranslationsError as e:
        raise HTTPException(400, _message(request, e)) from e
    name = f"translations-{lang}-{subject or 'all'}-{only}.json".replace("/", "-")
    return Response(
        json.dumps(data, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="{name}"'},
    )


@admin.post("/import")
async def import_(request: Request, user: CurrentUser = Depends(editor)):
    t = translator(request)
    form = await request.form()
    upload = form.get("file")
    site, default = _languages(request)
    try:
        raw = await upload.read() if upload is not None and hasattr(upload, "read") else b""
        data = json.loads(raw.decode("utf-8")) if raw else None
        written, refused, touched = service.import_(
            _state(request)["db"], _state(request)["kinds"], data, site, default
        )
        for subject, ids in touched.items():
            _state(request)["announce"](subject, ids, [data["locale"]])
    except (UnicodeDecodeError, json.JSONDecodeError):
        toast(request, t("This is not a Nest translations file."), "error")
        return RedirectResponse(f"{_base(request)}/", status_code=303)
    except TranslationsError as e:
        toast(request, _message(request, e), "error")
        return RedirectResponse(f"{_base(request)}/", status_code=303)
    toast(request, t.ngettext("{n} translation saved.", "{n} translations saved.", written))
    if refused:
        toast(request, t("Not saved: {list}", list="; ".join(refused[:5])), "error")
    return RedirectResponse(f"{_base(request)}/?lang={data.get('locale', '')}", status_code=303)
