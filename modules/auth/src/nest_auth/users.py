"""The users page of the admin panel: accounts, their roles, active or not."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_db import Database

from nest import admin_url, bound, render, toast, translator
from nest_auth.sessions import (
    AccountError,
    CurrentUser,
    account,
    close_all_sessions,
    list_accounts,
    update_account,
)
from nest_auth.web import require_role

admin = APIRouter()
administrator = require_role("admin")
PER_PAGE = 50


@admin.get("/")
def accounts(
    request: Request,
    q: str = "",
    page: int = 1,
    user: CurrentUser = Depends(administrator),
    db: Database = bound(Database),
):
    page = max(1, page)
    rows, total = list_accounts(db, q.strip(), limit=PER_PAGE, offset=(page - 1) * PER_PAGE)
    return render(
        request,
        "auth/users.html",
        fragment="rows",
        accounts=rows,
        total=total,
        q=q,
        page=page,
        pages=max(1, -(-total // PER_PAGE)),
        base=admin_url(request, "auth"),
    )


@admin.get("/{user_id:int}")
def edit(
    request: Request,
    user_id: int,
    user: CurrentUser = Depends(administrator),
    db: Database = bound(Database),
):
    acct = account(db, user_id)
    if acct is None:
        raise HTTPException(404)
    return render(request, "auth/user.html", acct=acct, error=None, base=admin_url(request, "auth"))


@admin.post("/{user_id:int}")
def save(
    request: Request,
    user_id: int,
    roles: str = Form(""),
    active: str = Form(""),
    user: CurrentUser = Depends(administrator),
    db: Database = bound(Database),
):
    try:
        update_account(
            db, user_id, roles=roles.replace(" ", ",").split(","), active=bool(active), by=user.id
        )
    except AccountError as e:
        acct = account(db, user_id)
        if acct is None:
            raise HTTPException(404) from None
        _ = translator(request)
        return render(
            request,
            "auth/user.html",
            status_code=400,
            acct=acct,
            error=_(e.message, **e.params),
            base=admin_url(request, "auth"),
        )
    toast(request, translator(request)("Saved."))
    return RedirectResponse(admin_url(request, "auth", f"{user_id}?saved=1"), status_code=303)


@admin.post("/{user_id:int}/sign-out")
def sign_out(
    request: Request,
    user_id: int,
    user: CurrentUser = Depends(administrator),
    db: Database = bound(Database),
):
    if account(db, user_id) is None:
        raise HTTPException(404)
    close_all_sessions(db, user_id)
    return RedirectResponse(admin_url(request, "auth", f"{user_id}?signed_out=1"), status_code=303)
