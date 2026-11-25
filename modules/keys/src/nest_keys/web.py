"""The keys module's pages (Romanian addresses under its route, /intrare in Voievodate):

/               start: play (the site's own first page), or I already have a character
                (its key, a code from another device)
/cheie          the key's link lands here (the code after # is read by the page, never
                sent in the address); the code typed
/nou            a new account (a site without its own way: a name), shown its key
/cont           the account: its key, its devices, adding one, signing out
/leaga/<token>  a device-adding link (asks before it signs in: links are prefetched)
/leaga          the 6 digits typed
"""

from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from markupsafe import Markup
from nest_auth import current_user, session_token, sign_in, token_id
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


def _site(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def key_link(request: Request, code: str) -> str:
    """The key as a link: the code after #, which browsers never send to the server."""
    return f"{_site(request)}{_base(request)}/cheie#{code}"


def qr_svg(text: str) -> Markup:
    import segno

    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=4, border=2, xmldecl=False, svgns=True)
    return Markup(out.getvalue().decode())


def _enter(request: Request, user: Any) -> Response:
    """Sign this browser in as ``user`` (a device's session, sliding for a year)."""
    st = _st(request)
    response = RedirectResponse(str(st["after"] or "/"), status_code=303)
    sign_in(request, response, user, days=int(st["device_days"] or 365))
    return response


def _tried(request: Request) -> int:
    """Seconds to wait when this address has tried too many codes; else 0."""
    t = _st(request)["tries"]
    key = f"keys|{_client(request)}"
    return t.window if t.blocked(key) else 0


def _failed(request: Request) -> None:
    _st(request)["tries"].fail(f"keys|{_client(request)}")


def pins_of(db: Any, request: Request) -> Any:
    from nest_keys import pins

    token = session_token(request)
    return pins.of(db, token_id(token)) if token else None


def show_key(request: Request, code: str, *, fresh: bool = True, status: int = 200) -> Response:
    return render(
        request,
        "keys/key.html",
        status_code=status,
        code=code,
        link=key_link(request, code),
        fresh=fresh,
        base=_base(request),
    )


@router.get("")
@router.get("/")
def start(request: Request):
    if current_user(request) is not None:
        return RedirectResponse(f"{_base(request)}/cont", status_code=303)
    return render(
        request, "keys/start.html", play=str(_st(request)["play"] or "/"), base=_base(request)
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
    user = service.by_key(db, cod)
    if user is None:
        _failed(request)
        return render(
            request, "keys/enter.html", status_code=400, base=_base(request), error="wrong"
        )
    return _enter(request, user)


@router.post("/nou")
def new_account(request: Request, nume: str = Form(""), db: Database = bound(Database)):
    """A new account for a site that has no way of its own (a game makes it as the character
    is named: ``nest_keys.start_account``)."""
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


class TooMany(Exception):
    """Too many new accounts from this address today."""


def start_account(request: Request, db: Any, name: str = "") -> tuple[Response, str, Any]:
    """For a site's own sign-up (a game naming a character): a new account signed in on this
    browser, its key's code to show the player once, and the account. Raises TooMany past
    the day's limit for the address. The response carries the session's cookie: copy it
    onto yours."""
    st = _st(request)
    key = f"new|{_client(request)}"
    if st["new_accounts"].blocked(key):
        raise TooMany()
    st["new_accounts"].fail(key)
    user, code = service.start(db, name)
    response = Response()
    sign_in(request, response, user, days=int(st["device_days"] or 365))
    return response, code, user


def starter(request: Request, db: Any, name: str = "") -> dict:
    """For another module (a game naming a character), through ``keys.starter``: a new
    account signed in on this browser: {"response": (carries the session's cookie),
    "user": CurrentUser, "code": the key's code, "link": the key as a link}. Raises TooMany."""
    response, code, user = start_account(request, db, name)
    return {"response": response, "user": user, "code": code, "link": key_link(request, code)}


@router.get("/cont")
def account(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        return RedirectResponse(f"{_base(request)}/", status_code=303)
    from nest_keys import passkeys

    key = service.key_of(db, user.id)
    return render(
        request,
        "keys/account.html",
        key=key,
        passkeys=passkeys.of(db, user.id),
        pin=pins_of(db, request),
        pin_said=request.query_params.get("pin", ""),
        pin_hours=int(float(_st(request)["pin_idle_hours"] or 12)),
        devices=service.devices(db, user.id, token_id(session_token(request))),
        base=_base(request),
    )


@router.post("/cheie/noua")
def new_key(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    return show_key(request, service.new_key(db, user.id))


@router.post("/cheie/salvata")
def key_saved(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    service.mark_saved(db, user.id)
    return RedirectResponse(f"{_base(request)}/cont", status_code=303)


@router.post("/dispozitiv/nou")
def add_device(request: Request, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    token, digits = service.pair_start(db, user.id)
    link = f"{_site(request)}{_base(request)}/leaga/{token}"
    return render(
        request,
        "keys/pair.html",
        link=link,
        digits=f"{digits[:3]} {digits[3:]}",
        qr=qr_svg(link),
        minutes=service.PAIRING_MINUTES,
        base=_base(request),
    )


@router.post("/dispozitiv/{session_id}/iesire")
def sign_out_device(request: Request, session_id: str, db: Database = bound(Database)):
    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    service.sign_out_device(db, user.id, session_id)
    return RedirectResponse(f"{_base(request)}/cont", status_code=303)


@router.get("/leaga/{token}")
def pair_link_page(request: Request, token: str):
    return render(request, "keys/link.html", token=token, base=_base(request), error="")


@router.get("/leaga")
def pair_code_page(request: Request):
    return render(request, "keys/link.html", token="", base=_base(request), error="")


@router.post("/leaga")
def pair(
    request: Request, token: str = Form(""), cod: str = Form(""), db: Database = bound(Database)
):
    if wait := _tried(request):
        return render(
            request,
            "keys/link.html",
            status_code=429,
            token="",
            base=_base(request),
            error=f"wait:{wait // 60 or 1}",
        )
    user = service.pair_use(db, token=token[:64], digits=cod[:12])
    if user is None:
        _failed(request)
        return render(
            request, "keys/link.html", status_code=400, token="", base=_base(request), error="wrong"
        )
    return _enter(request, user)


# --- passkeys (WebAuthn): JSON for the page's script ---------------------------------


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
    st = _st(request)
    response = JSONResponse({"ok": True, "go": str(st["after"] or "/")})
    sign_in(request, response, user, days=int(st["device_days"] or 365))
    return response


@router.post("/acces/{key_id}/sterge")
def passkey_remove(request: Request, key_id: str, db: Database = bound(Database)):
    from nest_keys import passkeys

    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    passkeys.remove(db, user.id, key_id)
    return RedirectResponse(f"{_base(request)}/cont", status_code=303)


# --- a device's PIN --------------------------------------------------------------------


def _next(value: str) -> str:
    value = value or "/"
    return (
        value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"
    )


def _this_session(request: Request) -> str:
    token = session_token(request)
    return token_id(token) if token else ""


@router.get("/pin")
def pin_page(request: Request, next: str = "/"):
    return render(request, "keys/pin.html", next=_next(next), base=_base(request), error="")


@router.post("/pin")
def pin_unlock(
    request: Request, pin: str = Form(""), next: str = Form("/"), db: Database = bound(Database)
):
    from nest_keys import pins

    sid = _this_session(request)
    if not sid:
        return RedirectResponse(f"{_base(request)}/", status_code=303)
    result = pins.unlock(db, sid, pin[:16])
    if result == "ok":
        return RedirectResponse(_next(next), status_code=303)
    if result == "out":
        response = RedirectResponse(f"{_base(request)}/?iesit=1", status_code=303)
        response.delete_cookie(pins.COOKIE, path="/")
        return response
    return render(
        request,
        "keys/pin.html",
        status_code=400,
        next=_next(next),
        base=_base(request),
        error=result,
    )


@router.post("/dispozitiv/pin")
def pin_set(
    request: Request, pin: str = Form(""), din_nou: str = Form(""), db: Database = bound(Database)
):
    from nest_keys import pins

    user = current_user(request)
    sid = _this_session(request)
    if user is None or not sid:
        raise HTTPException(403)
    if pin != din_nou:
        return RedirectResponse(f"{_base(request)}/cont?pin=diferit#pin-h", status_code=303)
    try:
        pins.set_pin(db, user.id, sid, pin)
    except pins.PinError as e:
        return RedirectResponse(f"{_base(request)}/cont?pin={e}#pin-h", status_code=303)
    return RedirectResponse(f"{_base(request)}/cont?pin=ok#pin-h", status_code=303)


@router.post("/dispozitiv/pin/sterge")
def pin_remove(request: Request, db: Database = bound(Database)):
    from nest_keys import pins

    user = current_user(request)
    if user is None:
        raise HTTPException(403)
    pins.remove(db, user.id, _this_session(request))
    return RedirectResponse(f"{_base(request)}/cont#pin-h", status_code=303)


@router.post("/iesire")
def sign_out_here(request: Request, db: Database = bound(Database)):
    """Sign this device out (a forgotten PIN: come back by the key or a passkey)."""
    from nest_auth import close_session

    from nest_keys import pins

    token = session_token(request)
    if token:
        pins.drop(db, token_id(token))
        close_session(db, token)
    response = RedirectResponse(f"{_base(request)}/", status_code=303)
    response.delete_cookie(pins.COOKIE, path="/")
    return response
