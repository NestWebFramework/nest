"""Safe defaults every application gets without asking.

* Security headers on every response: a strict Content-Security-Policy (no
  inline script, no eval), no framing, no MIME sniffing, a same-origin
  referrer.
* CSRF protection on every unsafe request to a module's routes: a signed token
  in an HttpOnly cookie, echoed by htmx in a header or by a plain form in a
  hidden field, compared in constant time; plus an Origin check.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE = "nest_csrf"
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"
FORM_MAX_FILES = 50  # the most files one form may send
FORM_MAX_FIELDS = 500  # and fields (an entry's editor, with its seo and translation fields)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


# What a package may add to the policy (a top-level ``csp:`` section of its module.yml):
# where its pictures, frames, media and requests may come from. Scripts and styles stay
# 'self' only, so no package can loosen what runs on a page.
CSP_EXTENDABLE = ("img-src", "frame-src", "media-src", "connect-src")
# The one exception for scripts: sources reviewed here, in Nest's core, that a package may
# let in (and only while the site's administrator asks for them: the seo module adds
# Google's tag server only while a Google Analytics ID is set). A script from elsewhere
# can do anything on a page, so this list stays short and is never a package's to grow.
CSP_SCRIPT_SOURCES = frozenset({"https://www.googletagmanager.com"})
_SOURCE = re.compile(r"^https://(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?(/[\w./-]*)?$")


class CspError(ValueError):
    pass


def build_csp(sections: list[tuple[str, Any]]) -> str:
    """The default policy, with the sources each package's ``csp:`` section adds.

    ``sections`` is [(package, {directive: [source, ...]})], as ModuleHost.sections
    gives it. A source is an https origin (a host, optionally a path); a bare
    wildcard, a keyword or a plain-http source is refused.
    """
    directives: dict[str, list[str]] = {}
    for part in DEFAULT_CSP.split(";"):
        name, *sources = part.split()
        directives[name] = sources
    problems = []
    for owner, section in sections:
        if not isinstance(section, dict):
            problems.append(f"{owner}: csp is a mapping of directive to sources")
            continue
        for directive, sources in section.items():
            if directive not in CSP_EXTENDABLE and directive != "script-src":
                problems.append(
                    f"{owner}: csp may extend {', '.join(CSP_EXTENDABLE)}, not '{directive}'"
                )
                continue
            if isinstance(sources, str):
                sources = [sources]
            target = directives.setdefault(directive, ["'self'"])
            for source in sources or []:
                source = str(source).strip().lower()
                if not _SOURCE.match(source):
                    problems.append(f"{owner}: '{source}' is not an https source csp accepts")
                elif directive == "script-src" and source not in CSP_SCRIPT_SOURCES:
                    problems.append(
                        f"{owner}: scripts stay the site's own; '{source}' is not one of the "
                        f"script sources Nest lets in ({', '.join(sorted(CSP_SCRIPT_SOURCES))})"
                    )
                elif source not in target:
                    target.append(source)
    if problems:
        raise CspError("; ".join(problems))
    return "; ".join(" ".join([name, *sources]) for name, sources in directives.items())


def local_path(value: str | None, fallback: str = "/") -> str:
    """Only a path on this site. An open redirect is how a phishing link borrows trust."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    if any(ord(ch) < 32 for ch in value) or urlsplit(value).netloc:
        return fallback
    return value


def _sign(secret: str, nonce: str) -> str:
    mac = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{nonce}.{mac}"


def _valid(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce = token.split(".", 1)[0]
    return hmac.compare_digest(_sign(secret, nonce), token)


ALLOW_HEADER = "x-nest-allow"


def allow(response: Any, *what: str) -> Any:
    """Loosen the page policy for one response, by name: "embed" (other sites may show it
    in a frame: a widget) and "geolocation" (the page may ask the browser where the reader
    is). Every other page keeps the strict policy."""
    known = {"embed", "geolocation"}
    unknown = set(what) - known
    if unknown:
        raise ValueError(f"cannot allow {', '.join(sorted(unknown))}")
    response.headers[ALLOW_HEADER] = ",".join(sorted(set(what)))
    return response


class SecurityMiddleware:
    """Pure ASGI, so it never buffers a streamed (SSE) response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret: str,
        secure_cookies: bool,
        csp: str | Callable[[], str] = DEFAULT_CSP,
    ):
        self.app = app
        self.secret = secret
        self.secure = secure_cookies
        self.csp = csp if callable(csp) else (lambda: csp)
        self.headers = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "same-origin",
            "cross-origin-opener-policy": "same-origin",
            "permissions-policy": "camera=(), microphone=(), geolocation=()",
        }
        if secure_cookies:
            self.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = None
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                jar = SimpleCookie()
                try:
                    jar.load(value.decode("latin-1"))
                except Exception:  # noqa: BLE001 - a malformed cookie is no cookie
                    continue
                if CSRF_COOKIE in jar:
                    token = jar[CSRF_COOKIE].value
        fresh = None
        if not _valid(self.secret, token):
            token = fresh = _sign(self.secret, secrets.token_urlsafe(24))
        state = scope.setdefault("state", {})
        state["csrf_token"] = token
        state["csrf_cookie_valid"] = fresh is None
        reading = scope.get("method") in ("GET", "HEAD")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                wants = {w.strip() for w in headers.get(ALLOW_HEADER, "").split(",") if w.strip()}
                if ALLOW_HEADER in headers:
                    del headers[ALLOW_HEADER]
                for key, value in self.headers.items():
                    if key not in headers:
                        if key == "x-frame-options" and "embed" in wants:
                            continue  # another site may frame it (a widget)
                        if key == "permissions-policy" and "geolocation" in wants:
                            value = value.replace("geolocation=()", "geolocation=(self)")
                        headers[key] = value
                if "content-security-policy" not in headers:
                    policy = self.csp()
                    if "embed" in wants:
                        policy = policy.replace("frame-ancestors 'none'", "frame-ancestors *")
                    headers["content-security-policy"] = policy
                page = headers.get("content-type", "").startswith("text/html")
                # A page that holds no form (it never wrote the token) gives no cookie: a
                # reader's page is the same for every reader, and a cache may keep it.
                quiet = reading and page and not state.get("csrf_used")
                if fresh and not quiet:
                    cookie = f"{CSRF_COOKIE}={fresh}; Path=/; HttpOnly; SameSite=Lax"
                    headers.append("set-cookie", cookie + ("; Secure" if self.secure else ""))
                if (
                    quiet
                    and message.get("status") == 200
                    and not state.get("user")
                    and "set-cookie" not in headers
                    and "cache-control" not in headers
                ):
                    headers["cache-control"] = "public, max-age=60, stale-while-revalidate=300"
                    headers.append("vary", "Cookie")  # the reader's language is a cookie
                elif page and state.get("user") and "cache-control" not in headers:
                    # a page made for a signed-in visitor: never kept by a shared cache, nor
                    # by the site's service worker (the pwa module) for reading offline
                    headers["cache-control"] = "private, no-cache"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _same_site(request: Request, origin: str) -> bool:
    """Whether a request's Origin is this site: the Host it came with, the host a proxy says
    it forwarded (X-Forwarded-Host, when nginx passes its own upstream as Host), or one of the
    names the site is served under (NEST_ALLOWED_HOSTS). The CSRF token is checked as well."""
    parts = urlsplit(origin)
    names = {request.headers.get("host", "")}
    forwarded = request.headers.get("x-forwarded-host", "")
    if forwarded:
        names.add(forwarded.split(",")[0].strip())
    nest = getattr(request.app.state, "nest", None)
    allowed = str(nest.environ.get("NEST_ALLOWED_HOSTS", "")) if nest is not None else ""
    names |= {h.strip() for h in allowed.split(",") if h.strip()}
    return parts.netloc in names or (parts.hostname or "") in names


async def csrf_protect(request: Request) -> None:
    """A dependency every module router gets: refuse a forged unsafe request."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin and origin != "null" and not _same_site(request, origin):
        raise HTTPException(403, "cross-origin request refused")
    if not request.state.csrf_cookie_valid:
        raise HTTPException(403, "CSRF cookie missing; reload the page")
    expected = request.state.csrf_token
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            # read before who sent it is known: within tight limits (and the body limit,
            # limits.BodyLimit); a script that uploads sends the token as a header instead
            form = await request.form(max_files=FORM_MAX_FILES, max_fields=FORM_MAX_FIELDS)
            value = form.get(CSRF_FIELD)
            sent = value if isinstance(value, str) else None
    if not sent or not hmac.compare_digest(expected, sent):
        raise HTTPException(403, "CSRF token missing or invalid")
