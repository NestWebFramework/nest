"""The keys module's pages (Romanian addresses under its route, /intrare in Voievodate):

/                start: play (the site's own first step), or come back with a passkey or
                 the key
/cheie           the key's link lands here (the code after # is read by the page, never
                 sent in the address); the code typed or pasted
/nou             a new account, for a site without its own first step (a name)
/cont            the account: how one comes back, a passkey, a new key, the other devices
/acces...        passkeys (JSON, for the page's script)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from nest_auth import current_user, session_token, sign_in
from nest_db import Database

from nest import bound, render
from nest.host import module_state
from nest_keys import service

router = APIRouter()


def _st(request: Request) -> dict[str, Any]:
    return module_state(request, "keys")


def _base(request: Request) -> str:
    return _st(request)["base"]


def _client(request: Request) -> str:
    return request.client.host if request.client else "-"


def key_link(request: Request, code: str) -> str:
    """The key as a link: the code after #, which browsers never send to the server."""
    return f"{str(request.base_url).rstrip('/')}{_base(request)}/cheie#{code}"


def _device(request: Request, response: Response, user: Any) -> None:
    """Sign this browser in as ``user`` (a device's session, sliding for a year)."""
    sign_in(request, response, user, days=int(_st(request)["device_days"] or 365))


def _tried(request: Request) -> int:
    """Seconds to wait when this address has tried too many keys or passkeys; else 0."""
    t = _st(request)["tries"]
    return t.window if t.blocked(f"keys|{_client(request)}") else 0


def _failed(request: Request) -> None:
    _st(request)["tries"].fail(f"keys|{_client(request)}")


def _after(request: Request) -> str:
    return str(_st(request)["after"] or "/")


# --- start, and coming back with the key ------------------------------------------------


@router.get("")
@router.get("/")
def start(request: Request):
    if current_user(request) is not None:
        return RedirectResponse(f"{_base(request)}/cont", status_code=303)
    return render(
        request,
        "keys/start.html",
        play=str(_st(request)["play"] or "/"),
        base=_base(request),
        error="",
    )


@router.get("/cheie")
def enter_key_page(request: Request):
    return render(request, "keys/enter.html", base=_base(request), error="")


@router.post("/cheie")
def enter_key(request: Request, cod: str = Form(""), db: Database = bound(Database)):
    if wait := _tried(request):
        return render(
            request,
            "keys/enter.html",
            status_code=429,
            base=_base(request),
            error=f"wait:{wait // 60 or 1}",
        )
    user = service.by_key(db, cod.split("#")[-1])  # the code, or the whole link pasted
    if user is None:
        _failed(request)
        return render(
            request, "keys/enter.html", status_code=400, base=_base(request), error="wrong"
        )
    response = RedirectResponse(_after(request), status_code=303)
    _device(request, response, user)
    return response


# --- a new account ---------------------------------------------------------------------


class TooMany(Exception):
    """Too many new accounts from this address today."""


def start_account(request: Request, db: Any, name: str = "") -> tuple[Response, str, Any]:
    """For a site's own first step (a game naming a character): a new account signed in on
    this browser, its key's code, and the account. Raises TooMany past the day's limit for
    the address. The response carries the session's cookie: copy it onto yours."""
    st = _st(request)
    key = f"new|{_client(request)}"
    if st["new_accounts"].blocked(key):
        raise TooMany()
    st["new_accounts"].fail(key)
    user, code = service.start(db, name)
    response = Response()
    _device(request, response, user)
    return response, code, user


def starter(request: Request, db: Any, name: str = "") -> dict:
    """For another module, through ``keys.starter``: {"response" (carries the session's
    cookie), "user", "code", "link"}. Raises TooMany."""
    response, code, user = start_account(request, db, name)
    return {"response": response, "user": user, "code": code, "link": key_link(request, code)}


def show_key(request: Request, code: str, status: int = 200) -> Response:
    return render(
        request,
        "keys/key.html",
        status_code=status,
        code=code,
        link=key_link(request, code),
        base=_base(request),
    )


@router.post("/nou")
def new_account(request: Request, nume: str = Form(""), db: Database = bound(Database)):
    """A new account for a site without a first step of its own (a game makes it as the
    character is named, through ``keys.starter``)."""
    if current_user(request) is not None:
        return RedirectResponse(f"{_base(request)}/cont", status_code=303)
    try:
        response, code, _user = start_account(request, db, nume)
    except TooMany:
        return render(
            request,
            "keys/start.html",
            status_code=429,
            base=_base(request),
            play=str(_st(request)["play"] or "/"),
            error="many",
        )
    page = show_key(request, code)
    for header, value in response.raw_headers:
        if header == b"set-cookie":
            page.raw_headers.append((header, value))
    return page


# --- the account -----------------------------------------------------------------------


@router.get("/cont")
def account(request: Request, db: Database = bound(Database)):
    from nest_keys import passkeys

    user = current_user(request)
    if user is None:
        return RedirectResponse(f"{_base(request)}/", status_code=303)
    key = service.key_of(db, user.id)
    return render(
        request,
        "keys/account.html",
        key_kept=bool(key and key.saved),
        passkeys=len(passkeys.of(db, user.id)),
        signed_out=request.query_params.get("iesit") == "1",
        base=_base(request),
    )


@router.post("/cheie/noua.json")
def new_key_json(request: Request, db: Database = bound(Database)):
    """A new key, for the page to download at once (the old one stops working); being
    downloaded, it counts as kept."""
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    code = service.new_key(db, user.id)
    service.mark_saved(db, user.id)
    return {"code": code, "link": key_link(request, code)}


@router.post("/cheie/salvata")
def key_saved(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    service.mark_saved(db, user.id)
    return RedirectResponse(_after(request), status_code=303)


@router.post("/dispozitive/iesire-toate")
def sign_out_others(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    service.sign_out_others(db, user.id, session_token(request))
    return RedirectResponse(f"{_base(request)}/cont?iesit=1", status_code=303)


# --- passkeys (WebAuthn): JSON for the page's script -------------------------------------


def _party(request: Request) -> tuple[str, str]:
    """The relying party's id (the site's host) and the origin the browser must report:
    the request's Origin, accepted only when it is this very host (Nest keeps the Host
    header to the allowed hosts)."""
    from urllib.parse import urlsplit

    host = (request.headers.get("host") or request.url.netloc).lower()
    origin = request.headers.get("origin") or ""
    if urlsplit(origin).netloc.lower() != host:
        raise HTTPException(403)
    return host.split(":")[0], origin


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400) from None
    if not isinstance(body, dict):
        raise HTTPException(400)
    return body


def _fail(e: Exception) -> JSONResponse:
    return JSONResponse({"ok": False, "why": str(e) or "refused"}, status_code=400)


@router.post("/acces/inregistrare/optiuni")
def passkey_register_options(request: Request, db: Database = bound(Database)):
    from nest_keys import passkeys

    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    rp_id, _ = _party(request)
    title = request.app.state.nest.title
    label = f"{title} · {user.name}" if user.name else f"{title} #{user.id}"
    return passkeys.register_options(db, user, rp_id, title, label)


@router.post("/acces/inregistrare")
async def passkey_register(request: Request, db: Database = bound(Database)):
    from starlette.concurrency import run_in_threadpool

    from nest_keys import passkeys

    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    rp_id, origin = _party(request)
    body = await _json(request)
    name = service.device_name(request.headers.get("user-agent", ""))
    try:
        await run_in_threadpool(
            passkeys.register,
            db,
            user,
            str(body.get("ticket") or ""),
            body.get("credential"),
            rp_id,
            origin,
            name,
        )
    except passkeys.PasskeyError as e:
        return _fail(e)
    return {"ok": True}


@router.post("/acces/optiuni")
def passkey_enter_options(request: Request, db: Database = bound(Database)):
    from nest_keys import passkeys

    rp_id, _ = _party(request)
    return passkeys.enter_options(db, rp_id)


@router.post("/acces")
async def passkey_enter(request: Request, db: Database = bound(Database)):
    from starlette.concurrency import run_in_threadpool

    from nest_keys import passkeys

    if wait := _tried(request):
        return JSONResponse(
            {"ok": False, "why": "wait", "minutes": wait // 60 or 1}, status_code=429
        )
    rp_id, origin = _party(request)
    body = await _json(request)
    try:
        user = await run_in_threadpool(
            passkeys.enter, db, str(body.get("ticket") or ""), body.get("credential"), rp_id, origin
        )
    except passkeys.PasskeyError as e:
        _failed(request)
        return _fail(e)
    response = JSONResponse({"ok": True, "go": _after(request)})
    _device(request, response, user)
    return response
