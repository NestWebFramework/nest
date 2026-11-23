"""An address per language (``application.language_urls: prefix``).

The default language is served at the site's root; every other one under its prefix:
``/category/stiai-ca/`` in Romanian, ``/en/category/stiai-ca/`` in English. A page has one
language at one address, which is what search engines index and caches keep.

On the way in, the prefix sets the request's language and is taken off the path, so no
module's routes change: the forum answers ``/forum/`` whether it was asked for in English or
not. ``/ro/...`` (the default's own prefix) is sent to ``/...`` for good.

On the way out, an English page's links to the site get the prefix back: its ``href``,
``action`` and htmx addresses, its own absolute addresses (a canonical link), and a
redirect's ``Location``. Files (``/assets/``, ``/media/``), the admin panel and Nest's own
addresses (``/_nest/``) are left as they are. Every page also says, in its head, where it
is in the other languages (``hreflang``), for search engines: the same path under each
prefix, or, when a module says otherwise (``request.state.alternates``, a translated
slug), where it says. A page showing the original's text for a missing translation
(``request.state.language_fallback``) keeps the original as its canonical.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

KEEP = (
    "/assets/",
    "/media/",
    "/_nest/",
    "/favicon",
    "/robots.txt",
    "/sitemap.xml",
    "/healthz",
    # the web app's (the pwa module): one address each, whatever the visitor's language
    "/manifest.webmanifest",
    "/sw.js",
    "/offline",
    "/.well-known/",
)
_ATTR = re.compile(
    rb'(\s(?:href|action|src|hx-get|hx-post|hx-put|hx-patch|hx-delete|hx-push-url|data-href)=")(/[^"]*)"'
)
_HEAD_END = re.compile(rb"</head>", re.I)


def with_prefix(path: str, locale: str, default: str) -> str:
    """``path`` (the site's own, unprefixed) as ``locale`` addresses it."""
    if locale == default:
        return path or "/"
    return f"/{locale}" + (path if path.startswith("/") else "/" + path)


class LanguageURLs:
    def __init__(
        self,
        app: ASGIApp,
        *,
        languages: list[str],
        default: str,
        keep: Callable[[], list[str]] = list,
        origin: Callable[[], str | None] = lambda: None,
    ):
        self.app, self.default = app, default
        self.languages = list(languages)
        self.prefixed = [lang for lang in self.languages if lang != default]
        self.keep, self.origin = keep, origin

    def _kept(self, path: str) -> bool:
        if path.startswith(KEEP):
            return True
        for root in self.keep():
            if root and (path == root or path.startswith(root.rstrip("/") + "/")):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        first = path.split("/", 2)[1] if path.count("/") >= 1 else ""
        if first == self.default:  # the default has no prefix: one address only
            rest = path[len(first) + 1 :] or "/"
            await _redirect(send, rest + _query(scope), 301)
            return
        if first in self.prefixed:
            rest = path[len(first) + 1 :]
            if not rest:  # /en → /en/
                await _redirect(send, f"/{first}/" + _query(scope), 301)
                return
            if self._kept(rest):  # files and the admin panel have one address
                await _redirect(send, rest + _query(scope), 301)
                return
            scope = dict(scope)
            scope["path"] = rest
            scope["raw_path"] = rest.encode()
            # the request's state is shared with the middleware around (the CSRF cookie is set
            # when a page wrote the form token): updated in place, never replaced
            scope.setdefault("state", {}).update(url_locale=first, url_prefix=f"/{first}")
            locale = first
        else:
            scope.setdefault("state", {}).update(url_locale=self.default, url_prefix="")
            locale = self.default
        if self._kept(scope["path"]):
            await self.app(scope, receive, send)
            return
        await self.app(scope, receive, self._sender(scope, send, locale))

    def _sender(self, scope: Scope, send: Send, locale: str) -> Send:
        prefix = "" if locale == self.default else f"/{locale}"
        start: dict[str, Any] = {}
        chunks: list[bytes] = []

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                html = any(k == b"content-type" and v.startswith(b"text/html") for k, v in headers)
                if prefix:
                    headers = [
                        (k, self._prefix_location(v, prefix)) if k == b"location" else (k, v)
                        for k, v in headers
                    ]
                message = {**message, "headers": headers}
                if not html or scope.get("method") not in ("GET", "HEAD", "POST"):
                    start["passthrough"] = True
                    await send(message)
                    return
                start["message"] = message
                return
            if message["type"] != "http.response.body" or start.get("passthrough"):
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = self._rewrite(b"".join(chunks), scope, prefix)
            head = start["message"]
            headers = [(k, v) for k, v in head["headers"] if k != b"content-length"]
            headers.append((b"content-length", str(len(body)).encode()))
            await send({**head, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        return wrapped

    def _prefix_location(self, value: bytes, prefix: str) -> bytes:
        text = value.decode("latin-1")
        already = any(text == f"/{lang}" or text.startswith(f"/{lang}/") for lang in self.prefixed)
        if (
            text.startswith("/")
            and not text.startswith("//")
            and not self._kept(text)
            and not already
        ):
            return (prefix + text).encode("latin-1")
        return value

    def _rewrite(self, body: bytes, scope: Scope, prefix: str) -> bytes:
        if prefix:
            pb = prefix.encode()
            prefixes = tuple(f"/{lang}/".encode() for lang in self.prefixed)

            def local(m: re.Match[bytes]) -> bytes:
                target = m.group(2)
                text = target.decode("utf-8", "replace")
                if target.startswith(b"//") or self._kept(text) or target.startswith(prefixes):
                    return m.group(0)
                return m.group(1) + pb + target + b'"'

            body = _ATTR.sub(local, body)
            # a page standing in for a missing translation (the original's text at this
            # language's address) points search engines at the original: its canonical stays
            fallback = scope.get("state", {}).get("language_fallback")
            for origin in [] if fallback else self._origins(scope):
                own = re.compile(rb'(="' + re.escape(origin.encode()) + rb")(/[^\"]*)\"")

                def absolute(m: re.Match[bytes]) -> bytes:
                    target = m.group(2)
                    if self._kept(target.decode("utf-8", "replace")) or target.startswith(prefixes):
                        return m.group(0)
                    return m.group(1) + pb + target + b'"'

                body = own.sub(absolute, body)
        if not re.search(rb'<link[^>]+rel="alternate"[^>]+hreflang=', body):  # not given already
            body = _HEAD_END.sub(lambda m: self._alternates(scope) + m.group(0), body, count=1)
        return body

    def _origins(self, scope: Scope) -> list[str]:
        found = []
        configured = self.origin()
        if configured:
            found.append(str(configured).rstrip("/"))
        host = _header(scope, b"host")
        if host:
            found.append(f"{scope.get('scheme', 'http')}://{host}")
        return list(dict.fromkeys(found))

    def _alternates(self, scope: Scope) -> bytes:
        """Where this page is in each language, for search engines."""
        origins = self._origins(scope)
        if not origins:
            return b""
        origin, path = origins[0], scope["path"]
        # A page whose address differs per language (a translated slug) says where it is in
        # each: request.state.alternates = {language: its path there, or None (not there)}.
        given = scope.get("state", {}).get("alternates")
        where = (
            {lang: given.get(lang) for lang in self.languages}
            if isinstance(given, dict)
            else dict.fromkeys(self.languages, path)
        )
        links = [
            f'<link rel="alternate" hreflang="{lang}" href="{origin}{with_prefix(p, lang, self.default)}">'
            for lang, p in where.items()
            if p
        ]
        if where.get(self.default):
            links.append(
                f'<link rel="alternate" hreflang="x-default" href="{origin}{where[self.default]}">'
            )
        return ("\n  ".join(links) + "\n").encode()


def _query(scope: Scope) -> str:
    q = scope.get("query_string", b"")
    return ("?" + q.decode("latin-1")) if q else ""


def _header(scope: Scope, name: bytes) -> str:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return ""


async def _redirect(send: Send, location: str, status: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})
