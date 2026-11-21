"""The registry over HTTP.

* ``/simple/`` and ``/simple/<project>/``: the Python package index uv and pip install
  from (PEP 503 pages, PEP 691 JSON when asked), each file's sha256 in its link.
* ``/files/<sha256>/<filename>``: a published file, never changing (kept a year).
* ``/api/v1/``: the catalog (what each package is for Nest), ``whoami``, ``upload``. The
  upload takes a token (``Authorization: Bearer``), never a cookie, so it needs no CSRF.
* ``/`` and ``/p/<name>``: the catalog to browse; ``/tokens``: an account's tokens.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from markupsafe import escape
from nest_auth import CurrentUser, active_user, require_user, users_by_ids
from starlette.concurrency import run_in_threadpool

from nest import render, toast, translator
from nest.host import module_state
from nest_registry import service
from nest_registry.service import PublishError

pages = APIRouter()  # the catalog, tokens: a browser's, with CSRF
api = APIRouter()  # the index, files, the API: tokens, not cookies
JSON_SIMPLE = "application/vnd.pypi.simple.v1+json"
YEAR = "public, max-age=31536000, immutable"


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "registry")


def _base(request: Request) -> str:
    return _state(request)["base"]


def public_url(request: Request) -> str:
    """The registry's address for the commands its pages show: its public_url setting, else
    the host a proxy forwarded, else the address the request came to (behind nginx that may
    be its upstream, 127.0.0.1)."""
    configured = str(_state(request)["settings"].get("public_url") or "").rstrip("/")
    if configured:
        return configured
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if forwarded:
        return f"{request.url.scheme}://{forwarded}{_base(request)}"
    return str(request.base_url).rstrip("/") + _base(request)


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return JSON_SIMPLE in accept or "application/vnd.pypi.simple.latest+json" in accept


# --- the package index ----------------------------------------------------------------------


@api.get("/simple/", include_in_schema=False)
def simple_root(request: Request) -> Response:
    names = service.projects(_state(request)["db"], viewer(request))
    if _wants_json(request):
        body = {"meta": {"api-version": "1.1"}, "projects": [{"name": n} for n in names]}
        return Response(json.dumps(body), media_type=JSON_SIMPLE)
    links = "".join(f'<a href="{escape(n)}/">{escape(n)}</a>\n' for n in names)
    return HTMLResponse(
        f'<!doctype html><html><head><meta name="pypi:repository-version" content="1.1">'
        f"<title>Simple index</title></head><body>\n{links}</body></html>"
    )


@api.get("/simple/{project}/", include_in_schema=False)
def simple_project(request: Request, project: str) -> Response:
    from packaging.utils import canonicalize_name  # noqa: PLC0415

    if canonicalize_name(project) != project:  # PEP 503: the normalised name is the address
        return RedirectResponse(
            f"{_base(request)}/simple/{canonicalize_name(project)}/", status_code=301
        )
    found = service.files_of(_state(request)["db"], project, viewer(request))
    if found is None:
        raise HTTPException(404)
    package, rows = found
    base = _base(request)
    if _wants_json(request):
        body = {
            "meta": {"api-version": "1.1"},
            "name": package.dist,
            "versions": sorted({r.version for r, _f in rows}, key=service._version_key),
            "files": [
                {
                    "filename": f.filename,
                    "url": f"{base}/files/{f.sha256}/{f.filename}",
                    "hashes": {"sha256": f.sha256},
                    "requires-python": r.requires_python or None,
                    "size": f.size,
                    "yanked": (r.yank_reason or True) if r.yanked else False,
                }
                for r, f in rows
            ],
        }
        return Response(json.dumps(body), media_type=JSON_SIMPLE)
    links = []
    for r, f in rows:
        attrs = f' data-requires-python="{escape(r.requires_python)}"' if r.requires_python else ""
        attrs += f' data-yanked="{escape(r.yank_reason)}"' if r.yanked else ""
        links.append(
            f'<a href="{base}/files/{f.sha256}/{escape(f.filename)}#sha256={f.sha256}"{attrs}>{escape(f.filename)}</a>'
        )
    return HTMLResponse(
        f'<!doctype html><html><head><meta name="pypi:repository-version" content="1.1">'
        f"<title>Links for {escape(package.dist)}</title></head><body>\n<h1>Links for {escape(package.dist)}</h1>\n"
        + "<br>\n".join(links)
        + "\n</body></html>"
    )


@api.get("/files/{sha}/{filename}", include_in_schema=False)
def file(request: Request, sha: str, filename: str) -> Response:
    row = service.file_by(_state(request)["db"], sha, filename, viewer(request))
    if row is None:
        raise HTTPException(404)
    storage = _state(request)["storage"]
    headers = {"Cache-Control": YEAR, "Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        storage.open(row.key), media_type="application/octet-stream", headers=headers
    )


# --- the API ------------------------------------------------------------------------------------


def _presented(request: Request) -> str | None:
    """The token a request presents: Bearer (nest), or Basic with __token__ (uv, pip)."""
    import base64  # noqa: PLC0415

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if auth.lower().startswith("basic "):
        try:
            user, _, secret = base64.b64decode(auth[6:].strip()).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        return secret if user == "__token__" else None
    return None


def viewer(request: Request) -> Any:
    """Who is asking, to see private packages: a token's account, else the signed-in one."""
    secret = _presented(request)
    if secret:
        db = _state(request)["db"]
        user_id = service.user_of(db, secret)
        return active_user(db, user_id) if user_id is not None else None
    return getattr(request.state, "user", None)


def _token_user(request: Request) -> Any:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            401,
            "a token is needed (Authorization: Bearer nrt_...)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    db = _state(request)["db"]
    user_id = service.user_of(db, auth[7:].strip())
    user = active_user(db, user_id) if user_id is not None else None  # a disabled account: no
    if user is None:
        raise HTTPException(
            401,
            "that token is not known here, or was revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@api.get("/api/v1/packages")
def api_packages(request: Request, q: str = "", type: str = "", nest: str = "") -> JSONResponse:  # noqa: A002
    """The catalog; with ?nest=<a nest-core version>, each package's newest release that
    works with it (packages with none left out)."""
    return JSONResponse(
        {"packages": service.catalog(_state(request)["db"], q, type, nest, viewer(request))}
    )


@api.get("/api/v1/packages/{name}")
def api_package(request: Request, name: str) -> JSONResponse:
    item = service.package(_state(request)["db"], name, viewer(request))
    if item is None:
        raise HTTPException(404)
    return JSONResponse(item)


@api.get("/api/v1/whoami")
def api_whoami(request: Request) -> JSONResponse:
    user = _token_user(request)
    publishers = str(_state(request)["settings"].get("publishers"))
    return JSONResponse(
        {
            "account": user.label,
            "admin": user.has("admin"),
            "may_publish": service.may_publish(user, publishers),
        }
    )


@api.post("/api/v1/upload")
async def api_upload(request: Request) -> JSONResponse:
    user = await run_in_threadpool(_token_user, request)
    state = _state(request)
    limit = int(state["settings"].get("max_upload_mb")) * 1024 * 1024
    form = await request.form(max_part_size=limit)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "send the file as the form field 'file'")
    data = await upload.read()
    fields = {k: str(form.get(k) or "") for k in ("signature", "key", "visibility")}
    try:
        done = await run_in_threadpool(
            service.publish,
            state["db"],
            state["storage"],
            user,
            upload.filename or "",
            data,
            official_prefix=str(state["settings"].get("official_prefix")),
            max_bytes=limit,
            publishers=str(state["settings"].get("publishers")),
            index_only=frozenset(
                x.strip() for x in str(state["settings"].get("index_only")).split(",") if x.strip()
            ),
            signature=fields["signature"],
            signer=fields["key"],
            require_signatures=bool(state["settings"].get("require_signatures")),
            visibility=fields["visibility"] or "public",
        )
    except PublishError as e:
        return JSONResponse({"detail": e.message}, status_code=e.status)
    done["url"] = f"{_base(request)}/p/{done['name']}"
    return JSONResponse(done, status_code=201)


@api.post("/api/v1/keys")
async def api_add_key(request: Request) -> JSONResponse:
    """Register a public key the account signs with (nest keygen --register)."""
    user = await run_in_threadpool(_token_user, request)
    body = await request.json()
    try:
        row = service.add_key(
            _state(request)["db"], user.id, str(body.get("public", "")), str(body.get("name", ""))
        )
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return JSONResponse({"fingerprint": row.fingerprint, "name": row.name}, status_code=201)


@api.post("/api/v1/packages/{name}/visibility")
async def api_visibility(request: Request, name: str) -> JSONResponse:
    user = await run_in_threadpool(_token_user, request)
    body = await request.json()
    try:
        service.set_visibility(_state(request)["db"], name, user, str(body.get("visibility", "")))
    except service.AccessError as e:
        return JSONResponse({"detail": str(e)}, status_code=404 if "no such" in str(e) else 403)
    return JSONResponse({"name": name, "visibility": body.get("visibility")})


@api.post("/api/v1/packages/{name}/{version}/yank")
async def api_yank(request: Request, name: str, version: str) -> JSONResponse:
    user = await run_in_threadpool(_token_user, request)
    body = await request.json()
    try:
        service.yank(
            _state(request)["db"],
            name,
            version,
            user,
            str(body.get("reason", "")),
            bool(body.get("undo")),
        )
    except service.AccessError as e:
        return JSONResponse({"detail": str(e)}, status_code=404 if "no " in str(e)[:3] else 403)
    return JSONResponse({"name": name, "version": version, "yanked": not body.get("undo")})


# --- pages ---------------------------------------------------------------------------------------


TYPES = ("module", "theme", "provider", "interface", "subsystem", "content")


@pages.get("/")
def index(request: Request, q: str = "", type: str = ""):  # noqa: A002
    db = _state(request)["db"]
    return render(
        request,
        "registry/index.html",
        fragment="results",
        items=service.catalog(db, q.strip(), type, "", viewer(request)),
        q=q,
        kind=type,
        types=TYPES,
        counts=service.counts(db),
        base=_base(request),
    )


@api.get("/p/{name}/screenshot", include_in_schema=False)
def package_screenshot(request: Request, name: str) -> Response:
    found = service.screenshot(_state(request)["db"], name, viewer(request))
    if found is None:
        raise HTTPException(404)
    key, media = found
    storage = _state(request)["storage"]
    return StreamingResponse(
        storage.open(key), media_type=media, headers={"Cache-Control": "public, max-age=3600"}
    )


@pages.get("/p/{name}")
def package_page(request: Request, name: str):
    from nest_auth import current_user  # noqa: PLC0415

    db = _state(request)["db"]
    item = service.package(db, name, viewer(request))
    if item is None:
        raise HTTPException(404)
    owner_id, maintainer_ids = service.people(db, name) or (item["owner_id"], [])
    who = users_by_ids(db, [owner_id, *maintainer_ids])
    me = current_user(request)
    return render(
        request,
        "registry/package.html",
        item=item,
        owner=who[owner_id].label if owner_id in who else "?",
        maintainers=[(i, who[i].label) for i in maintainer_ids if i in who],
        manages=me is not None and (me.id == owner_id or me.has("admin")),
        index_url=public_url(request) + "/simple/",
        base=_base(request),
    )


@pages.post("/p/{name}/maintainers")
def maintainer_add(
    request: Request, name: str, email: str = Form(""), user: CurrentUser = Depends(require_user)
):
    from nest_auth import find_user  # noqa: PLC0415

    db = _state(request)["db"]
    t = translator(request)
    found = find_user(db, email)
    if found is None:
        toast(request, t("No active account {email}.", email=email.strip()), "error")
    else:
        try:
            service.add_maintainer(db, name, user, found.id)
            toast(request, t("{who} may publish {name} now.", who=found.label, name=name))
        except service.AccessError as e:
            toast(request, t(str(e)), "error")
    return RedirectResponse(f"{_base(request)}/p/{name}", status_code=303)


@pages.post("/p/{name}/maintainers/{user_id}/remove")
def maintainer_remove(
    request: Request, name: str, user_id: int, user: CurrentUser = Depends(require_user)
):
    try:
        service.remove_maintainer(_state(request)["db"], name, user, user_id)
        toast(request, translator(request)("The maintainer is removed."))
    except service.AccessError as e:
        toast(request, translator(request)(str(e)), "error")
    return RedirectResponse(f"{_base(request)}/p/{name}", status_code=303)


def _may_publish(request: Request, user: Any) -> bool:
    return service.may_publish(user, str(_state(request)["settings"].get("publishers")))


@pages.get("/tokens")
def tokens_page(request: Request, user: CurrentUser = Depends(require_user)):
    db = _state(request)["db"]
    return render(
        request,
        "registry/tokens.html",
        tokens=service.tokens_of(db, user.id),
        keys=service.keys_of(db, user.id),
        secret=None,
        allowed=_may_publish(request, user),
        registry=public_url(request),
        base=_base(request),
    )


@pages.post("/tokens")
def tokens_create(
    request: Request, name: str = Form(""), user: CurrentUser = Depends(require_user)
):
    db = _state(request)["db"]
    t = translator(request)
    if not _may_publish(request, user):
        raise HTTPException(
            403,
            t(
                "This account may not publish here; the registry's administrators approve publishers."
            ),
        )
    try:
        secret, _row = service.make_token(db, user.id, name)
    except ValueError as e:
        toast(request, t(str(e)), "error")
        return RedirectResponse(f"{_base(request)}/tokens", status_code=303)
    return render(
        request,
        "registry/tokens.html",
        tokens=service.tokens_of(db, user.id),
        keys=service.keys_of(db, user.id),
        secret=secret,
        allowed=True,
        registry=public_url(request),
        base=_base(request),
    )


@pages.post("/keys")
def keys_add(
    request: Request,
    public: str = Form(""),
    name: str = Form(""),
    user: CurrentUser = Depends(require_user),
):
    t = translator(request)
    if not _may_publish(request, user):
        raise HTTPException(403)
    try:
        service.add_key(_state(request)["db"], user.id, public, name)
        toast(request, t("The signing key is registered."))
    except ValueError as e:
        toast(request, t(str(e)), "error")
    return RedirectResponse(f"{_base(request)}/tokens", status_code=303)


@pages.post("/keys/{key_id}/revoke")
def keys_revoke(request: Request, key_id: int, user: CurrentUser = Depends(require_user)):
    service.revoke_key(_state(request)["db"], user.id, key_id)
    toast(request, translator(request)("The signing key is revoked."))
    return RedirectResponse(f"{_base(request)}/tokens", status_code=303)


@pages.post("/p/{name}/visibility")
def page_visibility(
    request: Request,
    name: str,
    visibility: str = Form(""),
    user: CurrentUser = Depends(require_user),
):
    t = translator(request)
    try:
        service.set_visibility(_state(request)["db"], name, user, visibility)
        toast(request, t("{name} is {visibility} now.", name=name, visibility=t(visibility)))
    except service.AccessError as e:
        toast(request, t(str(e)), "error")
    return RedirectResponse(f"{_base(request)}/p/{name}", status_code=303)


@pages.post("/p/{name}/{version}/yank")
def page_yank(
    request: Request,
    name: str,
    version: str,
    reason: str = Form(""),
    undo: str = Form(""),
    user: CurrentUser = Depends(require_user),
):
    t = translator(request)
    try:
        service.yank(_state(request)["db"], name, version, user, reason, bool(undo))
        toast(
            request,
            t("{version} is back.", version=version)
            if undo
            else t("{version} is withdrawn.", version=version),
        )
    except service.AccessError as e:
        toast(request, t(str(e)), "error")
    return RedirectResponse(f"{_base(request)}/p/{name}", status_code=303)


@pages.post("/tokens/{token_id}/revoke")
def tokens_revoke(request: Request, token_id: int, user: CurrentUser = Depends(require_user)):
    service.revoke(_state(request)["db"], user.id, token_id)
    toast(request, translator(request)("The token is revoked."))
    return RedirectResponse(f"{_base(request)}/tokens", status_code=303)
