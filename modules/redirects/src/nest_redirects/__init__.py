"""Old addresses sent on to new ones.

A fallback: asked only when no route and no earlier fallback answered, so a
page that exists always wins over a redirect pointing away from it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from nest_auth import CurrentUser, require_role
from nest_db import Database

from nest import ModuleHost, admin_url, bound, is_htmx, render, translator
from nest_redirects import service
from nest_redirects.service import RedirectError

__all__ = ["service"]

router = APIRouter()
editor = require_role("editor")


def _base(request: Request) -> str:
    return admin_url(request, "redirects")


@router.get("/")
def index(
    request: Request,
    q: str = "",
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    return render(
        request,
        "redirects/index.html",
        fragment="rows",
        redirects=service.listing(db, q.strip()),
        q=q,
        base=_base(request),
        error=None,
        values={},
    )


@router.post("/")
async def create(
    request: Request, user: CurrentUser = Depends(editor), db: Database = bound(Database)
):
    form = await request.form()
    values = {k: str(form.get(k, "")) for k in ("source", "target", "status", "note")}
    try:
        status = int(values["status"] or 301)
        service.add(db, values["source"], values["target"], status, values["note"])
    except (RedirectError, ValueError) as e:
        message = (
            translator(request)(e.message, **e.params) if isinstance(e, RedirectError) else str(e)
        )
        return render(
            request,
            "redirects/index.html",
            redirects=service.listing(db),
            q="",
            base=_base(request),
            error=message,
            values=values,
            status_code=200 if is_htmx(request) else 400,
        )
    return RedirectResponse(f"{_base(request)}/", status_code=303)


@router.post("/{redirect_id:int}/delete")
def delete(
    request: Request,
    redirect_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    service.remove(db, redirect_id)
    if is_htmx(request):
        return Response("", media_type="text/html")
    return RedirectResponse(f"{_base(request)}/", status_code=303)


def answer(request: Request) -> Response | None:
    db = request.app.state.nest.bindings.get("nest.db")
    r = service.find(db, request.url.path, request.url.query)
    if r is None:
        return None
    service.hit(db, r.id)
    if r.status == 410:
        raise HTTPException(410)
    return RedirectResponse(r.target, status_code=r.status)


def setup(host: ModuleHost) -> None:
    host.admin(router)  # all its pages are in the admin panel, at <admin route>/redirects
    host.fallback(answer, priority=-10)
