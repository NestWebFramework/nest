"""Stored files over HTTP, the address of each, and pictures at the size a page needs.

``/media/<key>`` is the file as it was stored. ``/media/<key>?w=640`` is a
picture made at most 640 pixels wide, as WebP, the first time someone asks for
it, then kept in the store beside the others (under ``_sized/``) and served from
there. Only a few widths are made (SIZES; any other is taken up to the next
one), so nobody can fill the disk by asking for every width there is.
"""

from __future__ import annotations

import contextlib
import io
import re
import threading
from typing import Any
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from nest_storage import Storage, StorageError

from nest import ModuleHost, bound
from nest.host import module_state
from nest_media.clean import ImageError
from nest_media.clean import clean as clean_image

__all__ = [
    "SIZES",
    "ImageError",
    "clean_image",
    "forget_sizes",
    "media_base",
    "media_srcset",
    "media_url",
    "responsive_images",
]

router = APIRouter()
ACTIVE = ("text/html", "image/svg", "application/xhtml", "text/xml", "application/xml")
SIZES = (320, 640, 960, 1280, 1920)
RASTER = ("image/jpeg", "image/png", "image/webp")
SIZED = "_sized"
MAX_PIXELS = 50_000_000  # a picture larger than this (a decompression bomb) is sent as it is
WEEK = "public, max-age=604800"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _width(w: int | None) -> int | None:
    if not w or w <= 0:
        return None
    return next((s for s in SIZES if s >= w), SIZES[-1])


def _url(base: str, key: str, width: int | None = None) -> str:
    if not key:
        return ""
    w = _width(width)
    return f"{base}/{quote(key)}" + (f"?w={w}" if w else "")


def _srcset(base: str, key: str) -> str:
    return ", ".join(f"{_url(base, key, s)} {s}w" for s in SIZES) if key else ""


def media_base(request: Request) -> str:
    """Where stored files are served in this application ("" when media is at /)."""
    return module_state(request, "media")["base"]


def media_url(request: Request, key: str, width: int | None = None) -> str:
    """The address of a stored file in this application ('' for no key); with a width,
    of the picture made that wide (for a picture; anything else comes as it is)."""
    return _url(module_state(request, "media")["base"], key, width)


def media_srcset(request: Request, key: str) -> str:
    """A srcset of a stored picture at every width media makes."""
    return _srcset(module_state(request, "media")["base"], key)


def sized_key(key: str, width: int) -> str:
    return f"{SIZED}/{width}/{key}.webp"


def forget_sizes(storage: Storage, key: str) -> None:
    """Remove the sized copies of a picture (when it is replaced or deleted)."""
    for width in SIZES:
        with contextlib.suppress(StorageError):
            storage.delete(sized_key(key, width))


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        if len(_locks) > 1024:  # only the ones being made matter
            for k in [k for k, v in _locks.items() if not v.locked()]:
                del _locks[k]
        return _locks.setdefault(key, threading.Lock())


def _make(storage: Storage, key: str, width: int) -> str | None:
    """The sized copy's key, made now if it is not there yet; None when it cannot be."""
    target = sized_key(key, width)
    if storage.stat(target) is not None:
        return target
    with _lock(target):
        if storage.stat(target) is not None:  # made while we waited
            return target
        from PIL import Image, ImageOps  # noqa: PLC0415 - only a sized picture needs it

        try:
            with storage.open(key) as f, Image.open(f) as img:
                if img.width * img.height > MAX_PIXELS:
                    return None
                pic = ImageOps.exif_transpose(img)
                if pic.mode not in ("RGB", "RGBA"):
                    pic = pic.convert("RGBA" if "transparency" in pic.info else "RGB")
                pic.thumbnail((width, width * 4))
                out = io.BytesIO()
                pic.save(out, "WEBP", quality=80, method=4)
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
        storage.put(target, out.getvalue(), "image/webp")
        return target


def _send(storage: Storage, key: str, content_type: str) -> Any:
    headers = {"Cache-Control": WEEK}
    if content_type.startswith(ACTIVE):
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    path = storage.local_path(key)
    if path:
        return FileResponse(path, media_type=content_type, headers=headers)
    return StreamingResponse(storage.open(key), media_type=content_type, headers=headers)


@router.api_route("/{key:path}", methods=["GET", "HEAD"])  # crawlers and link checkers ask HEAD
def serve(key: str, w: int | None = None, storage: Storage = bound(Storage)) -> Any:
    try:
        stat = storage.stat(key)
    except StorageError:
        raise HTTPException(404) from None
    if stat is None:
        raise HTTPException(404)
    width = _width(w)
    if width and stat.content_type in RASTER and not key.startswith(SIZED + "/"):
        sized = _make(storage, key, width)
        if sized is not None:
            return _send(storage, sized, "image/webp")
    return _send(storage, key, stat.content_type)


# --- pictures in rich text -------------------------------------------------------

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r'\ssrc="([^"]+)"', re.I)
SIZES_ATTR = "(max-width: 48rem) 100vw, 48rem"


def responsive_images(markup: str, base: str) -> str:
    """Each stored picture in rich text with a srcset, loaded lazily, so a phone downloads
    a picture its width and nobody downloads the ones they never scroll to."""
    prefix = f"{base}/"

    def one(m: re.Match[str]) -> str:
        tag = m.group(0)
        src = _SRC.search(tag)
        if not src or " srcset=" in tag.lower() or not src.group(1).startswith(prefix):
            return tag
        key = unquote(src.group(1)[len(prefix) :].split("?", 1)[0])
        if not key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return tag
        extra = f' srcset="{_srcset(base, key)}" sizes="{SIZES_ATTR}"'
        if " loading=" not in tag.lower():
            extra += ' loading="lazy"'
        extra += ' decoding="async"'
        return tag[:4] + extra + tag[4:]

    return _IMG.sub(one, markup or "")


def setup(host: ModuleHost) -> None:
    base = "" if host.route in (None, "/") else host.route
    host.state["base"] = base
    host.answer("media.base", lambda _key: base)  # for modules that do not depend on media

    @host.context
    def _media(request: Request) -> dict[str, Any]:
        return {
            "media_url": lambda key, width=None: _url(base, key, width),
            "media_srcset": lambda key: _srcset(base, key),
        }

    host.mount(router)
