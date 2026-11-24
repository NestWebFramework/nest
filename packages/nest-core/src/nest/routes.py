"""Calls between sites that run side by side: straight to the other's container, not out
through the internet and back.

    NEST_LOCAL_ROUTES="gari.ro=http://nest-gari:8000, transportul.ro=http://nest-transportul:8000"

A module that asks another site (``https://gari.ro/cfr/api/v1/...``) opens it with
``routes.urlopen``: when the site's host is in the list, the request goes to the local
address instead, saying it is for the public host (``Host: gari.ro``, ``X-Forwarded-Proto:
https``), so the answer is the same as from outside, its links the public ones. When the
local address does not answer, the public one is asked, as without the list.
"""

from __future__ import annotations

import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ENV = "NEST_LOCAL_ROUTES"
_cache: tuple[str, dict[str, str]] = ("", {})
_lock = threading.Lock()


def table(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The public host → local address list (``host=http://name:port``, comma separated)."""
    global _cache
    raw = (environ if environ is not None else os.environ).get(ENV, "")
    if environ is None and raw == _cache[0]:
        return _cache[1]
    out: dict[str, str] = {}
    for part in raw.split(","):
        host, _, local = part.strip().partition("=")
        host, local = host.strip().lower(), local.strip().rstrip("/")
        u = urllib.parse.urlsplit(local)
        if host and u.scheme in ("http", "https") and u.netloc and not u.path:
            out[host] = local
    if environ is None:
        with _lock:
            _cache = (raw, out)
    return out


def local(url: str, environ: dict[str, str] | None = None) -> tuple[str, str] | None:
    """The local address for ``url`` and the public host it stands for, or None."""
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    target = table(environ).get(host)
    if target is None or u.port not in (None, 443, 80):
        return None
    rest = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
    return target + rest, host


def urlopen(request: urllib.request.Request | str, timeout: float = 10) -> Any:
    """``urllib.request.urlopen``, through the local address when there is one."""
    req = (
        request if isinstance(request, urllib.request.Request) else urllib.request.Request(request)
    )
    found = local(req.full_url)
    if found is not None:
        address, host = found
        inner = urllib.request.Request(
            address,
            data=req.data,
            headers={**dict(req.header_items()), "Host": host, "X-Forwarded-Proto": "https"},
            method=req.get_method(),
        )
        try:
            return urllib.request.urlopen(inner, timeout=timeout)  # noqa: S310 - our own sites
        except urllib.error.HTTPError:
            raise  # it answered: its answer stands (a 404 is a 404)
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, TimeoutError) or isinstance(e, TimeoutError):
                raise  # it is there but slow: asking again from outside would only add to it
            # not there (no such name, nothing listening: moved, stopped): the public address
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - the caller's URL
