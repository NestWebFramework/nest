"""Stored files over HTTP, and the address of each."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from nest_storage import Storage, StorageError

from nest import ModuleHost, bound
from nest.host import module_state

__all__ = ["media_url"]

router = APIRouter()
ACTIVE = ("text/html", "image/svg", "application/xhtml", "text/xml", "application/xml")


def media_url(request: Request, key: str) -> str:
    """The address of a stored file in this application ('' for no key)."""
    if not key:
        return ""
    return f"{module_state(request, 'media')['base']}/{quote(key)}"


@router.get("/{key:path}")
def serve(key: str, storage: Storage = bound(Storage)) -> Any:
    try:
        stat = storage.stat(key)
    except StorageError:
        raise HTTPException(404) from None
    if stat is None:
        raise HTTPException(404)
    headers = {"Cache-Control": "public, max-age=604800"}
    if stat.content_type.startswith(ACTIVE):
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    path = storage.local_path(key)
    if path:
        return FileResponse(path, media_type=stat.content_type, headers=headers)
    return StreamingResponse(storage.open(key), media_type=stat.content_type, headers=headers)


def setup(host: ModuleHost) -> None:
    base = "" if host.route in (None, "/") else host.route
    host.state["base"] = base

    @host.context
    def _media(request: Request) -> dict[str, Any]:
        return {"media_url": lambda key: f"{base}/{quote(key)}" if key else ""}

    host.mount(router)
