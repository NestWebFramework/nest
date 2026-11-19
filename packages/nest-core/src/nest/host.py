"""The host: an application's plan turned into one running FastAPI service.

``create_app`` reads the application's manifest, discovers the catalog, checks
every contract, resolves and orders the packages, binds interfaces, then gives
each module a ``ModuleHost``: its view of the application. A module mounts its
router at the route the application chose, renders templates, reads its own
settings, and reaches a host facility (workspace, realtime) only if its
manifest asked for it. A required module that fails stops the start; an
optional one starts degraded and says why on the health page.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from jinja2 import TemplateNotFound
from markupsafe import Markup, escape
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from nest import composition
from nest.bind import Bindings, ProviderContext, build
from nest.catalog import Catalog, Entry
from nest.composition import Choice
from nest.contract import load_contracts
from nest.engine import ROLES, EngineGate, EngineProxy
from nest.i18n import ADMIN_LOCALE_COOKIE, LOCALE_COOKIE, Catalogs, LocaleMiddleware, translator
from nest.loader import import_main, import_object
from nest.manifest import load_manifest
from nest.realtime import Broker, Topic
from nest.resolve import Plan, Unit, plan
from nest.security import (
    CSRF_FIELD,
    CspError,
    SecurityMiddleware,
    build_csp,
    csrf_protect,
    local_path,
)
from nest.settings import Namespaced, SettingsStore
from nest.shortcodes import Shortcodes
from nest.templating import is_htmx, make_environment, render_block
from nest.workspace import environment, is_production, resolve_workspace, secret_key

log = logging.getLogger("nest")

Hook = Callable[[], Any | Awaitable[Any]]


_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


class _Token:
    """The form token, written into a page only when the page writes it: then (and only
    then) the response sets its cookie, and the page is no reader's page to cache."""

    __slots__ = ("_state", "_value")

    def __init__(self, state: dict[str, Any], value: str) -> None:
        self._state, self._value = state, value

    def _used(self) -> str:
        self._state["csrf_used"] = True
        return self._value

    def __str__(self) -> str:
        return str(self._used())

    def __html__(self) -> str:
        value = self._used()
        return value if isinstance(value, Markup) else str(escape(value))

    def __bool__(self) -> bool:
        return bool(self._value)


class HostError(Exception):
    pass


class Live:
    """A value read again each time (a setting, see ModuleHost.live)."""

    __slots__ = ("read",)

    def __init__(self, read: Callable[[], Any]):
        self.read = read


class LiveState(dict):
    """A module's state: as a dict, but a Live value is read when it is asked for."""

    def __getitem__(self, key: str) -> Any:
        value = super().__getitem__(key)
        return value.read() if isinstance(value, Live) else value

    def get(self, key: str, default: Any = None) -> Any:  # noqa: SIM401 - reads a Live value
        if key not in self:
            return default
        return self[key]


@dataclass
class ModuleState:
    name: str
    type: str
    version: str
    route: str | None
    state: str = "pending"
    reason: str | None = None


@dataclass
class AdminPage:
    """A module's pages in the admin panel, mounted at <admin route>/<module>."""

    module: str
    router: APIRouter
    title: str
    order: int = 50
    role: str = "admin"  # who sees it (the "admin" role sees everything)
    description: str = ""
    base: str = ""  # where it was mounted


class Nest:
    """Everything an application holds at run time; ``app.state.nest``."""

    def __init__(
        self,
        plan: Plan,
        bindings: Bindings,
        workspace: Path,
        environ: Mapping[str, str],
        secret: str,
    ):
        self.plan = plan
        self.bindings = bindings
        self.workspace = workspace
        self.environ = environ
        self.secret = secret
        self.production = is_production(environ)
        # under nest serve with a one-process module: "engine" holds its state, "web" passes
        # its requests to the engine; "" is one process doing everything (nest run)
        self.role = str(environ.get("NEST_ROLE", "")).strip().lower()
        if self.role not in ROLES:
            raise HostError(f"NEST_ROLE is engine or web, not '{self.role}'")
        self.manifest = plan.app.manifest
        self.name = self.manifest.name
        application = self.manifest.application
        self.title = (
            (application.title if application else None) or self.manifest.module.title or self.name
        )
        self.broker = Broker()
        self.shortcodes = Shortcodes()
        self.settings = SettingsStore(workspace / "data" / "settings.conf", self.name, environ)
        self.states: dict[str, ModuleState] = {}
        # Per-application, per-module state. A module keeps what it needs at run
        # time here, never in module-level globals, so two applications in one
        # process (or one test after another) never share it.
        self.module_state: dict[str, dict[str, Any]] = {}
        self.reloader: Any = None  # a Reloadable, when the server runs one (nest run)
        self.app: FastAPI | None = None
        self._context: list[Callable[[Request], Mapping[str, Any]]] = []
        self.admin_pages: list[AdminPage] = []  # what modules give the admin panel
        self.admin_root: str | None = None  # where the admin panel is (the admin module's route)
        self._fallbacks: list[tuple[int, int, str, Callable[[Request], Any]]] = []
        self._lookups: dict[str, list[tuple[str, Callable[[Any], Any]]]] = {}
        self._middleware: list[tuple[type, dict[str, Any]]] = []
        self._startup: list[Hook] = []
        self._shutdown: list[Hook] = []
        self._background: list[Callable[[], Awaitable[Any]]] = []
        # an asset's address carries its module's version and its files' last change, so a
        # browser that keeps it a year (immutable) still gets a changed stylesheet at once
        self._bundles: dict[str, tuple[str, bytes, float]] = {}
        self._bundle_checked: dict[str, float] = {}
        self._versions = {}
        for u in plan.units:
            folder = u.entry.manifest.folder(u.entry.manifest.static, "static")
            newest = (
                max((f.stat().st_mtime for f in folder.rglob("*") if f.is_file()), default=0)
                if folder is not None
                else 0
            )
            version = u.entry.manifest.module.version
            self._versions[u.name] = f"{version}-{int(newest):x}" if newest else version
        # The page policy, with the sources the packages' csp: sections add (a map's tiles,
        # a video's frames); the application's own last.
        csp = [
            (u.name, u.entry.manifest.raw["csp"])
            for u in plan.units
            if "csp" in u.entry.manifest.raw
        ]
        if "csp" in self.manifest.raw:
            csp.append((self.name, self.manifest.raw["csp"]))
        self.settings_checks: dict[str, Callable[[dict[str, Any]], list[str]]] = {}
        self._csp_sections = csp
        self._csp_runtime: dict[tuple[str, str], tuple[str, str]] = {}
        try:
            self.csp = build_csp(csp)
        except CspError as e:
            raise HostError(str(e)) from None
        app_static = plan.app.manifest.folder(plan.app.manifest.static, "static")
        if app_static is not None:  # the application's own files (a client it builds)
            newest = max(
                (f.stat().st_mtime for f in app_static.rglob("*") if f.is_file()), default=0
            )
            self._versions[plan.app.manifest.module.name] = (
                f"{plan.app.manifest.module.version}-{int(newest)}"
            )
        module_dirs: dict[str, Path] = {}
        for unit in plan.units:
            folder = unit.entry.manifest.folder(unit.entry.manifest.templates, "templates")
            if folder is not None and unit.entry is not plan.theme:
                module_dirs[unit.name] = folder
        theme_dir = None
        if plan.theme is not None:
            theme_dir = plan.theme.manifest.folder(plan.theme.manifest.templates, "templates")
        self.templates = make_environment(
            plan.app.root, theme_dir, module_dirs, reload=not self.production
        )
        languages = application.languages if application else ["en"]
        default = (application.default_language if application else None) or languages[0]
        self.site_languages = list(languages)
        self.admin_languages = list(
            (application.admin_languages if application else None) or languages
        )
        self.catalogs = Catalogs([*languages, *self.admin_languages], default)
        for unit in plan.units:
            for item in unit.entry.manifest.locales:
                self.catalogs.load(unit.name, item.locale, unit.entry.root / item.file)
        for item in self.manifest.locales:  # the application's own wording wins
            self.catalogs.load(self.name, item.locale, plan.app.root / item.file)
        fallback = self.catalogs.translator()
        self.templates.globals.update(
            asset=self.asset,
            app={"name": self.name, "title": self.title},
            _=fallback.gettext,
            ngettext=fallback.ngettext,
            locale=fallback.locale,
            languages=self.catalogs.languages,
            styles=[self.bundle_url("site")],
        )

    # --- stylesheets: one file a page ---------------------------------------------------
    #
    # A page loads one stylesheet: the theme's, then each module's (in the plan's order),
    # then the application's, put together when the application starts (so the later
    # restyles the earlier, as separate files did). The admin panel's has the modules'
    # admin_styles too, before the application's. Each is served at /assets/_bundle/<name>.css?v=<its hash>
    # and kept a year; while developing, a changed stylesheet makes it again.

    def _style_files(self, kind: str) -> list[tuple[str, str, Path]]:
        """(module, its path in the module's static folder, the file), in loading order."""
        plan = self.plan
        files: list[tuple[str, str, Path]] = []

        def add(entry: Any, sheets: list[str]) -> None:
            folder = entry.manifest.folder(entry.manifest.static, "static")
            if folder is None:
                return
            name = entry.manifest.name
            files.extend((name, s, folder / s) for s in sheets if (folder / s).is_file())

        # the theme, each module's look, (in the admin panel, each module's admin look,)
        # and the application's own last: it restyles everything before it
        if plan.theme is not None:
            add(plan.theme, plan.theme.manifest.styles)
        for u in plan.units:
            if u.entry is not plan.theme:
                add(u.entry, u.entry.manifest.styles)
        if kind == "admin":
            for u in plan.units:
                add(u.entry, u.entry.manifest.admin_styles)
            add(plan.app, self.manifest.admin_styles)
        add(plan.app, self.manifest.styles)
        return files

    def _build_bundle(self, kind: str) -> tuple[str, bytes, float]:
        files = self._style_files(kind)
        parts = []
        for module, rel, f in files:
            # a stylesheet's relative url() (its fonts, its pictures) is made absolute: the
            # combined file is served from another folder
            base = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""

            def absolute(m: re.Match[str], module: str = module, base: str = base) -> str:
                target = m.group(2).strip()
                if target.startswith(("data:", "http:", "https:", "/", "#")):
                    return m.group(0)
                return f'url("{self.asset(module, base + target)}")'

            text = _CSS_URL.sub(absolute, f.read_text(encoding="utf-8"))
            parts.append(f"/* {module}: {rel} */\n{text}\n")
        body = "".join(parts).encode("utf-8")
        newest = max((f.stat().st_mtime for _m, _r, f in files), default=0.0)
        return hashlib.sha256(body).hexdigest()[:12], body, newest

    def bundle(self, kind: str) -> tuple[str, bytes]:
        """The stylesheet ``kind`` ("site" or "admin"): its hash and its text."""
        found = self._bundles.get(kind)
        if found is None or (not self.production and self._bundle_stale(kind, found[2])):
            found = self._bundles[kind] = self._build_bundle(kind)
        return found[0], found[1]

    def _bundle_stale(self, kind: str, built: float) -> bool:
        now = time.monotonic()
        if now - self._bundle_checked.get(kind, 0.0) < 1.0:
            return False
        self._bundle_checked[kind] = now
        return (
            max((f.stat().st_mtime for _m, _r, f in self._style_files(kind)), default=0.0) > built
        )

    def bundle_url(self, kind: str) -> str:
        return f"/assets/_bundle/{kind}.css?v={self.bundle(kind)[0]}"

    def asset(self, module: str, path: str) -> str:
        """The URL of a module's static file, versioned so caches can keep it."""
        if module not in self._versions:
            raise LookupError(f"no module '{module}' in this application")
        return f"/assets/{module}/{path}?v={self._versions[module]}"

    def template_context(self, request: Request) -> dict[str, Any]:
        state = request.scope.setdefault("state", {})
        token = _Token(state, request.state.csrf_token)
        field = _Token(
            state,
            Markup(
                f'<input type="hidden" name="{CSRF_FIELD}" value="{escape(request.state.csrf_token)}">'
            ),
        )
        context: dict[str, Any] = {}
        for provide in self._context:
            context.update(provide(request))
        t = translator(request)
        in_admin = bool(request.scope.get("state", {}).get("in_admin"))
        styles = [self.bundle_url("admin" if in_admin else "site")]  # one file, either way
        context.update(
            languages=self.site_languages,  # the site's switch offers these
            admin_languages=self.admin_languages,  # the admin panel's switch, these
            in_admin=in_admin,
            styles=styles,  # the site's stylesheet, and in the admin panel its own
        )
        context.update(
            # any module's shortcode, where an application's template wants it:
            # {{ shortcodes('[map]') }}, {{ shortcodes('[album slug="sat"]') }}
            shortcodes=lambda text: self.shortcodes.expand(text, request),
            request=request,
            csrf_token=token,
            csrf_field=field,
            is_htmx=is_htmx(request),
            _=t.gettext,
            ngettext=t.ngettext,
            locale=t.locale,
        )
        return context

    def lookup(self, name: str, key: Any) -> Any:
        """Ask the modules that answer ``name`` about ``key``; the first answer wins.

        How modules find each other's records without importing each other: the
        content module answers "wordpress.post" (an old post id → its entry), so a
        comments importer can attach WordPress comments to the right page.
        """
        for _owner, fn in self._lookups.get(name, []):
            answer = fn(key)
            if answer is not None:
                return answer
        return None

    def allow_source(self, owner: str, directive: str, source: str, slot: str = "") -> None:
        """A source the page policy takes while the application runs (a map's tiles, set
        in the admin panel), checked as a manifest's csp: is. One per owner and slot: a
        new one replaces the old, so a changed setting does not leave the old host open."""
        key = (owner, slot or directive)
        if self._csp_runtime.get(key) == (directive, source):
            return
        runtime = {**self._csp_runtime, key: (directive, source)}
        extra = [(o, {d: [s]}) for (o, _slot), (d, s) in runtime.items() if s]
        self.csp = build_csp([*self._csp_sections, *extra])  # CspError if not allowed
        self._csp_runtime = runtime

    def gather(self, name: str, key: Any = None) -> list[Any]:
        """Every module's answer to ``name`` (those that answered), in the plan's order.

        Where ``lookup`` wants one record, ``gather`` collects from all: the maps
        module gathers "map.points" from every module that has places to show.
        """
        found = []
        for owner, fn in self._lookups.get(name, []):
            try:
                answer = fn(key)
            except Exception:
                log.exception("%s failed to answer %s", owner, name)
                continue
            if answer is not None:
                found.append(answer)
        return found

    def answered(self, name: str) -> bool:
        """Whether any module answers ``name`` (so another may rely on it instead of its own way)."""
        return bool(self._lookups.get(name))

    def render_block(self, name: str, block: str, **context: Any) -> str:
        """A fragment rendered outside a request, for an SSE event."""
        return render_block(self.templates, name, block, context)

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI):
        threads = self.environ.get("NEST_THREADS", "")
        if threads.isdigit() and int(threads) > 0:
            # the pool the synchronous handlers run in: under Python's lock more threads
            # bring no speed, only waiting turns; nest serve sizes it (serve: threads)
            import anyio.to_thread  # noqa: PLC0415

            anyio.to_thread.current_default_thread_limiter().total_tokens = int(threads)
        for hook in self._startup:
            await _maybe(hook())
        relays = self.bindings.by_interface.get("nest.pubsub") or []
        relay = relays[0].impl if relays else None
        tasks = [
            asyncio.create_task(fn(), name=getattr(fn, "__name__", "task"))
            for fn in [*self.broker.tasks(relay, f"realtime:{self.name}"), *self._background]
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for hook in reversed(self._shutdown):
                try:
                    await _maybe(hook())
                except Exception:  # noqa: BLE001 - one bad hook must not stop the others
                    log.exception("shutdown hook failed")
            for provider in reversed(self.bindings.providers()):
                for method in ("aclose", "close", "dispose"):
                    close = getattr(provider.impl, method, None)
                    if callable(close):
                        try:
                            await _maybe(close())
                        except Exception:  # noqa: BLE001 - keep closing the others
                            log.exception("%s failed to close", provider.name)
                        break


SINGLE_RETRY_S = 5.0


def _single(
    task: Callable[[], Awaitable[Any]], path: Path, name: str
) -> Callable[[], Awaitable[Any]]:
    """The task, run only while this process holds the lock file (an flock: the system
    lets it go when the process ends, however it ends). Elsewhere the task just runs."""

    async def run() -> Any:
        try:
            import fcntl  # noqa: PLC0415 - POSIX; elsewhere there is one process anyway
        except ImportError:
            return await task()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(SINGLE_RETRY_S)  # another worker has it
            log.info("%s: this worker (pid %d) runs it", name, os.getpid())
            try:
                return await task()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    run.__name__ = getattr(task, "__name__", "task")
    return run


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class ModuleRealtime:
    """A module's view of the broker: it registers and publishes its own topics."""

    def __init__(self, broker: Broker, owner: str):
        self._broker = broker
        self._owner = owner

    def topic(self, name: str, **kwargs: Any) -> Topic:
        return self._broker.register(name, self._owner, **kwargs)

    def publish(self, topic: str, event: str, data: str, *, local: bool = False) -> None:
        """To everyone following ``topic`` on every worker (``local``: on this one only)."""
        registered = self._broker.find(topic)
        if registered is not None and registered.owner != self._owner:
            raise HostError(
                f"{self._owner} cannot publish to '{topic}', which {registered.owner} owns"
            )
        self._broker.publish(topic, event, data, local=local)

    def subscribers(self, topic: str) -> int:
        """Who follows ``topic`` on this worker (see listening)."""
        return self._broker.subscribers(topic)

    def listening(self, topic: str) -> bool:
        """Whether anyone may follow ``topic``, on any worker."""
        return self._broker.listening(topic)


class ModuleHost:
    """What a module sees of the application that includes it."""

    def __init__(self, nest: Nest, unit: Unit):
        self._nest = nest
        self._unit = unit
        self.name = unit.name
        self.manifest = unit.entry.manifest
        self.version = self.manifest.module.version
        self.route = unit.instance.route if unit.instance else None
        self.config: dict[str, Any] = dict(unit.instance.config) if unit.instance else {}
        self.settings = Namespaced(nest.settings, unit.name)
        self.log = logging.getLogger(f"nest.{unit.name}")

    @property
    def production(self) -> bool:
        return self._nest.production

    @property
    def admin_root(self) -> str | None:
        """Where the admin panel is ("" at /; None without one). Known once every module is
        set up: read it in a request or a lookup, not while setting up."""
        return self._nest.admin_root

    @property
    def app_title(self) -> str:
        """The application's title."""
        return self._nest.title

    @property
    def role(self) -> str:
        """ "engine" (this process holds the one-process modules' state and serves them),
        "web" (a worker: it passes their requests to the engine and must not open their
        state), or "" (one process doing everything)."""
        return self._nest.role

    def check_settings(self, fn: Callable[[dict[str, Any]], list[str]]) -> Callable:
        """``fn(values)`` judges this module's settings before the admin panel saves them:
        ``values`` is every setting as it would be, and what it returns are the problems
        (already in the reader's words), none to save."""
        self._nest.settings_checks[self.name] = fn
        return fn

    def allow_source(self, directive: str, source: str, slot: str = "") -> None:
        """Let pages load from ``source`` (an https origin) for ``directive`` (img-src,
        frame-src, media-src, connect-src), decided while running; CspError if refused."""
        self._nest.allow_source(self.name, directive, source, slot)

    def sign(self, value: str) -> str:
        """``value`` with a signature only this application can make (for a cookie): what
        comes back through ``unsign`` was not changed on the way."""
        mac = hmac.new(self._key(), value.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{value}.{mac}"

    def unsign(self, token: str) -> str | None:
        value, _, mac = (token or "").rpartition(".")
        if not value:
            return None
        good = hmac.new(self._key(), value.encode(), hashlib.sha256).hexdigest()[:32]
        return value if hmac.compare_digest(good, mac) else None

    def _key(self) -> bytes:  # one key per module: what one signs, another cannot pass off
        return hashlib.sha256(f"{self._nest.secret}:{self.name}".encode()).digest()

    def _require(self, facility: str) -> None:
        if facility not in self.manifest.requires.host:
            raise HostError(
                f"{self.name} uses the '{facility}' facility; add it to requires.host in its module.yml"
            )

    @property
    def workspace(self) -> Path:
        self._require("workspace")
        return self._nest.workspace

    @property
    def realtime(self) -> ModuleRealtime:
        self._require("realtime")
        return ModuleRealtime(self._nest.broker, self.name)

    def bound(self, key: str | type) -> Any:
        """The provider bound to an interface this module declared it requires."""
        name = key if isinstance(key, str) else self._nest.bindings.protocols.get(key, str(key))
        if name not in self.manifest.requires.interfaces:
            raise HostError(f"{self.name} uses {name}; add it to requires.interfaces")
        return self._nest.bindings.get(name)

    def bound_if(self, name: str, *, shared: bool = False) -> Any:
        """The provider bound to an interface the module can do without, or None when the
        application binds none. ``shared``: only one every worker sees, not one that keeps
        its values in each process (cache-memory), for what several workers must agree on."""
        providers = self._nest.bindings.by_interface.get(name) or []
        if not providers:
            return None
        if shared:
            unit = self._nest.plan.unit(providers[0].name)
            if unit is not None and getattr(unit.entry.manifest, "process_local", False):
                return None
        return providers[0].impl

    def mount(self, router: APIRouter) -> None:
        """Serve ``router`` at the route the application chose for this module."""
        if self.route is None:
            raise HostError(f"{self.name} has no route; an application must include it with one")
        prefix = "" if self.route == "/" else self.route
        assert self._nest.app is not None
        self._nest.app.include_router(router, prefix=prefix, dependencies=[Depends(csrf_protect)])

    def serve_at_root(self, router: APIRouter) -> None:
        """Serve ``router`` at the site's root, whatever this module's route: for the files
        a site answers at fixed addresses (/sitemap.xml, /robots.txt, /.well-known/...)."""
        assert self._nest.app is not None
        self._nest.app.include_router(router, dependencies=[Depends(csrf_protect)])

    def admin(self, router: APIRouter) -> AdminPage:
        """Give the admin panel this module's pages (its manifest's admin: says title, order, role).

        They are mounted at <admin route>/<module> once every module is set
        up, if the application includes the admin module; links to them come
        from ``admin_url``.
        """
        spec = self.manifest.raw.get("admin") or {}
        page = AdminPage(
            self.name,
            router,
            str(spec.get("title") or self.manifest.module.title or self.name),
            int(spec.get("order", 50)),
            str(spec.get("role", "admin")),
            str(spec.get("description", "")),
        )
        self._nest.admin_pages.append(page)
        return page

    def claim_admin(self) -> None:
        """This module is the admin panel: the others' admin pages are mounted under its route."""
        if self.route is None:
            raise HostError(f"{self.name} is the admin panel and needs a route")
        if self._nest.admin_root is not None:
            raise HostError("two modules claim the admin panel")
        self._nest.admin_root = "" if self.route == "/" else self.route

    def url(self, path: str = "") -> str:
        base = "" if self.route in (None, "/") else self.route
        return f"{base}/{path.lstrip('/')}" if path else (base or "/")

    def render_block(self, name: str, block: str, **context: Any) -> str:
        return self._nest.render_block(name, block, **context)

    def on_startup(self, fn: Hook) -> Hook:
        self._nest._startup.append(fn)
        return fn

    def on_shutdown(self, fn: Hook) -> Hook:
        self._nest._shutdown.append(fn)
        return fn

    def background(
        self, fn: Callable[[], Awaitable[Any]] | None = None, *, single: bool = False
    ) -> Any:
        """A task that runs from startup until shutdown: ``@host.background``.

        Under nest serve each worker runs it. ``@host.background(single=True)`` runs it in
        one worker of the workspace at a time (a nightly clean-up, a feed fetched every
        hour): the others wait, and one takes over if that worker stops."""

        def register(task: Callable[[], Awaitable[Any]]) -> Callable[[], Awaitable[Any]]:
            if single:
                name = f"{self.name}.{getattr(task, '__name__', 'task')}"
                lock = self._nest.workspace / "run" / f"{name}.lock"
                self._nest._background.append(_single(task, lock, name))
            else:
                self._nest._background.append(task)
            return task

        return register(fn) if fn is not None else register

    @property
    def state(self) -> dict[str, Any]:
        """This module's run-time state in this application (instead of globals). A value
        made with ``host.live`` is read again each time it is asked for."""
        found = self._nest.module_state.get(self.name)
        if not isinstance(found, LiveState):
            found = self._nest.module_state[self.name] = LiveState(found or {})
        return found

    def live(self, key: str, kind: Callable[[Any], Any] = lambda v: v) -> Live:
        """A setting for ``host.state``, read when it is used, so a change made in the admin
        panel applies at once: ``host.state.update(per_page=host.live("per_page", int))``."""
        settings = self.settings
        return Live(lambda: kind(settings.get(key)))

    def context(self, fn: Callable[[Request], Mapping[str, Any]]) -> Callable:
        """Add values to every page's template context (``user``, for the auth module)."""
        self._nest._context.append(fn)
        return fn

    def lookup(self, name: str, key: Any = None) -> Any:
        """Ask the application's modules (see Nest.lookup); how a module finds another's service."""
        return self._nest.lookup(name, key)

    def answer(self, name: str, fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Answer a lookup other modules may ask (see Nest.lookup)."""
        self._nest._lookups.setdefault(name, []).append((self.name, fn))
        return fn

    def packages(self, type_: str | None = None) -> list[Any]:
        """The manifests of the application's packages (of one type), read-only.

        In the order the application lists them (those only pulled in as
        dependencies first), so a later content pack overrides an earlier one.
        How a game subsystem finds the content packs' files: each manifest has
        its ``root`` folder and its ``raw`` sections.
        """
        listed = {i.name: n for n, i in enumerate(self._nest.plan.app.manifest.modules)}
        units = [u for u in self._nest.plan.units if type_ is None or u.entry.type == type_]
        units.sort(key=lambda u: listed.get(u.name, -1))
        return [u.entry.manifest for u in units]

    def has_module(self, name: str) -> bool:
        """Whether the application includes a package of that name (to cooperate, not depend)."""
        return self._nest.plan.unit(name) is not None

    def shortcode(self, name: str, fn: Callable[[dict[str, str], Any], str] | None = None) -> Any:
        """Answer ``[name ...]`` in rich text: ``host.shortcode("album", fn)`` or as a decorator."""

        def register(handler: Callable[[dict[str, str], Any], str]) -> Callable:
            self._nest.shortcodes.register(name, self.name, handler)
            return handler

        return register(fn) if fn is not None else register

    def template_filter(self, name: str, fn: Callable[..., Any]) -> None:
        """Add a Jinja filter, named for every template of the application."""
        if name in self._nest.templates.filters:
            raise HostError(f"{self.name}: the template filter '{name}' already exists")
        self._nest.templates.filters[name] = fn

    def fallback(
        self, fn: Callable[[Request], Any], *, priority: int = 0
    ) -> Callable[[Request], Any]:
        """Answer a GET that no route matched: return a response, or None to pass it on.

        Higher ``priority`` is asked first; among equals, in start order. Pages a
        module stores answer before redirects away from them (content uses 10,
        redirects -10). This is how a module serves paths it
        stores rather than declares (a CMS page at /history/the-church/) without
        a catch-all route that would shadow every module mounted after it. A
        blocking fallback is run in the thread pool.
        """
        fallbacks = self._nest._fallbacks
        fallbacks.append((-priority, len(fallbacks), self.name, fn))
        fallbacks.sort(key=lambda f: (f[0], f[1]))
        return fn

    def sections(self, key: str) -> list[tuple[str, Any]]:
        """A top-level manifest section as every package of the plan writes it, then the app's."""
        found = [
            (u.name, u.entry.manifest.raw[key])
            for u in self._nest.plan.units
            if key in u.entry.manifest.raw
        ]
        if key in self._nest.manifest.raw:
            found.append((self._nest.name, self._nest.manifest.raw[key]))
        return found

    def add_middleware(self, cls: type, **options: Any) -> None:
        """Wrap the application in an ASGI middleware, inside the security layer."""
        self._nest._middleware.append((cls, options))


def admin_url(request: Request, module: str, path: str = "") -> str:
    """Where a module's admin pages are (the admin panel's route, then the module's name)."""
    root = request.app.state.nest.admin_root
    if root is None:
        raise HostError("this application has no admin panel (include the admin module)")
    base = f"{root}/{module}"
    return f"{base}/{path.lstrip('/')}" if path else base


def module_state(request: Request, module: str) -> dict[str, Any]:
    """A module's run-time state, from a request (for dependencies a module exports)."""
    return request.app.state.nest.module_state.setdefault(module, {})


class _OptionalFailed(Exception):
    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason
        super().__init__(f"{name}: {reason}")


def create_app(
    app_dir: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    choices: dict[str, Choice] | None = None,
) -> FastAPI:
    """The application in ``app_dir``, with the modules its workspace chose (``choices``
    instead, to try a composition before keeping it). An optional module that fails to set
    up is left out: the application is made again without it, and says so."""
    without: dict[str, str] = {}
    while True:
        try:
            app = _create_app(app_dir, environ, choices, without)
        except _OptionalFailed as e:
            if e.name in without:
                raise HostError(f"{e.name} failed to set up: {e.reason}") from e
            log.error(
                "%s failed to set up (%s); it is optional: starting without it", e.name, e.reason
            )
            without[e.name] = e.reason
            continue
        nest = app.state.nest
        for name, reason in without.items():
            nest.states[name] = ModuleState(name, "module", "", None, "degraded", reason)
        return app


def _create_app(
    app_dir: str | Path,
    environ: Mapping[str, str] | None,
    choices: dict[str, Choice] | None,
    without: dict[str, str],
) -> FastAPI:
    app_root = Path(app_dir).resolve()
    manifest = load_manifest(app_root)
    base_env = dict(os.environ if environ is None else environ)
    workspace = resolve_workspace(manifest.name, base_env)
    chosen = dict(composition.load(workspace) if choices is None else choices)
    for name in without:
        chosen[name] = Choice(enabled=False)
    try:
        manifest = manifest.model_copy(update={"modules": composition.compose(manifest, chosen)})
    except composition.CompositionError as e:
        raise HostError(str(e)) from e
    app_entry = Entry(manifest=manifest, source="application")
    catalog = Catalog.discover(app_root)
    for problem in catalog.problems:
        log.warning("catalog: %s", problem)
    the_plan = plan(app_entry, catalog, load_contracts())
    for note in the_plan.notes:
        log.warning("%s", note)

    env = environment(workspace, base_env)
    context = ProviderContext(app=manifest.name, workspace=workspace, production=is_production(env))
    bindings = build(the_plan, env, context)
    nest = Nest(the_plan, bindings, workspace, env, secret_key(workspace, env))

    dev_docs = None if nest.production else "/_nest/docs"
    app = FastAPI(
        title=nest.title,
        lifespan=nest.lifespan,
        docs_url=dev_docs,
        redoc_url=None,
        openapi_url=None if nest.production else "/_nest/openapi.json",
    )
    app.state.nest = nest
    nest.app = app
    _core_routes(app, nest)

    for unit in the_plan.units:
        hook = unit.entry.manifest.startup
        if hook:
            try:
                import_object(hook, unit.entry)(nest)
            except Exception as e:
                raise HostError(f"{unit.name}: its startup hook failed: {e}") from e

    for unit in the_plan.units:
        entry = unit.entry
        nest.states[unit.name] = ModuleState(
            unit.name,
            entry.type,
            entry.manifest.module.version,
            unit.instance.route if unit.instance else None,
        )
        static = entry.manifest.folder(entry.manifest.static, "static")
        if static is not None:
            app.mount(
                f"/assets/{unit.name}",
                VersionedStatic(directory=static),
                name=f"assets:{unit.name}",
            )
    app_name = the_plan.app.manifest.module.name
    app_static = the_plan.app.manifest.folder(the_plan.app.manifest.static, "static")
    if app_static is not None and app_name not in {u.name for u in the_plan.units}:
        app.mount(
            f"/assets/{app_name}", VersionedStatic(directory=app_static), name=f"assets:{app_name}"
        )
    for unit in the_plan.units:
        entry = unit.entry
        # Every package with code that runs in the application is set up: modules,
        # themes and an ecosystem's own types (a game subsystem); interfaces and
        # providers are not, they are bound.
        if entry.type not in ("interface", "provider", "application"):
            nest.settings.declare(
                unit.name, entry.manifest.settings, unit.instance.config if unit.instance else None
            )
            try:
                _setup(nest, unit)
            except _OptionalFailed:
                close_providers(nest)  # this attempt is thrown away; the next opens its own
                raise
        else:
            nest.states[unit.name].state = "ready"

    if nest.admin_pages and nest.admin_root is None:
        log.warning(
            "%s: %s give admin pages, but no module is the admin panel (include the admin module)",
            nest.name,
            ", ".join(p.module for p in nest.admin_pages),
        )
    elif nest.admin_root is not None:
        for page in sorted(nest.admin_pages, key=lambda p: (p.order, p.module)):
            page.base = f"{nest.admin_root}/{page.module}"
            app.include_router(page.router, prefix=page.base, dependencies=[Depends(csrf_protect)])

    for cls, options in nest._middleware:
        app.add_middleware(cls, **options)
    app.add_middleware(
        LocaleMiddleware,
        catalogs=nest.catalogs,
        site=nest.site_languages,
        admin=nest.admin_languages,
        admin_root=lambda: nest.admin_root,
        browser=bool(nest.manifest.application.browser_language)
        if nest.manifest.application
        else True,
    )
    hosts = [h.strip() for h in nest.environ.get("NEST_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if hosts:  # a request for any other host is refused (400); the health check asks locally
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*hosts, "localhost", "127.0.0.1"])
    # Pages and SVG shrink about tenfold; SSE streams are left alone by Starlette.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # Added last, so outermost: every response gets the headers, whatever a module did.
    app.add_middleware(
        SecurityMiddleware,
        secret=nest.secret,
        secure_cookies=nest.production,
        csp=lambda: nest.csp,  # read per response: a module may add a source while running
    )
    if nest.role == "web" and nest.environ.get("NEST_ENGINE_URL"):
        # outermost: the engine's answers go out as the engine made them
        app.add_middleware(EngineProxy, nest=nest, url=nest.environ["NEST_ENGINE_URL"])
    elif nest.role == "engine":
        app.add_middleware(EngineGate, secret=nest.secret)
    log.info("%s: %d packages ready, workspace %s", nest.name, len(the_plan.units), workspace)
    return app


def _setup(nest: Nest, unit: Unit) -> None:
    state = nest.states[unit.name]
    try:
        module = import_main(unit.entry)
        setup = getattr(module, "setup", None) if module is not None else None
        if setup is not None:
            setup(ModuleHost(nest, unit))
        state.state = "ready"
    except Exception as e:
        if unit.instance is not None and unit.instance.optional:
            # what it registered before failing must not stay: the application is made
            # again without it (create_app)
            raise _OptionalFailed(unit.name, f"{type(e).__name__}: {e}") from e
        raise HostError(f"{unit.name} failed to set up: {type(e).__name__}: {e}") from e


def close_providers(nest: Nest) -> None:
    """Close what the providers opened, outside the event loop (a database's pool before a
    fork, an application made only to be checked)."""
    import contextlib  # noqa: PLC0415

    for provider in nest.bindings.providers():
        for name in ("dispose", "close"):
            closing = getattr(provider.impl, name, None)
            if callable(closing):
                with contextlib.suppress(Exception):
                    closing()
                break


class VersionedStatic(StaticFiles):
    """A module's static files. Asked for with its version (?v=, as asset() writes every
    address), a file never changes, so browsers and proxies keep it for a year."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        scope = args[2] if len(args) > 2 else kwargs.get("scope", {})
        if b"v=" in scope.get("query_string", b""):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response


def _core_routes(app: FastAPI, nest: Nest) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # A GET that no route matched (no endpoint in scope) is offered to the
        # modules' fallbacks before it becomes a 404.
        if (
            exc.status_code == 404
            and "endpoint" not in request.scope
            and request.method in ("GET", "HEAD")
        ):
            for _priority, _order, owner, fn in nest._fallbacks:
                try:
                    if inspect.iscoroutinefunction(fn):
                        answer = await fn(request)
                    else:
                        answer = await run_in_threadpool(fn, request)
                except StarletteHTTPException as raised:
                    exc = raised
                    break
                except Exception:
                    log.exception("fallback of %s failed", owner)
                    exc = StarletteHTTPException(500)
                    break
                if answer is not None:
                    return answer
        return _error_page(request, nest, exc)

    @app.get("/assets/_bundle/{kind}.css", include_in_schema=False)
    async def stylesheet(kind: str, request: Request) -> Response:
        if kind not in ("site", "admin"):
            return Response(status_code=404)
        digest, body = await run_in_threadpool(nest.bundle, kind)
        versioned = request.query_params.get("v") == digest
        return Response(
            body,
            media_type="text/css; charset=utf-8",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable" if versioned else "no-cache",
                "ETag": f'"{digest}"',
            },
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/_nest/health", include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        client = request.client.host if request.client else ""
        if nest.production and client not in ("127.0.0.1", "::1"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        checks: dict[str, bool] = {}
        for provider in nest.bindings.providers():
            ping = getattr(provider.impl, "ping", None)
            if inspect.iscoroutinefunction(ping):
                checks[provider.name] = bool(await ping())
            elif callable(ping):  # a blocking check (a database round trip) runs off the loop
                checks[provider.name] = bool(await run_in_threadpool(ping))
        return JSONResponse(
            {
                "application": nest.name,
                "modules": [vars(s) for s in nest.states.values()],
                "bindings": {
                    iface: [p.name for p in providers]
                    for iface, providers in nest.bindings.by_interface.items()
                },
                "checks": checks,
            },
            status_code=200 if all(checks.values()) else 503,
        )

    @app.get("/_nest/language", include_in_schema=False)
    async def choose_language_link(request: Request) -> RedirectResponse:
        """The language switch as links: no form, so a reader's page carries no token (a
        language is no secret to forge)."""
        return _language(request, dict(request.query_params))

    @app.post("/_nest/language", include_in_schema=False, dependencies=[Depends(csrf_protect)])
    async def choose_language(request: Request) -> RedirectResponse:
        return _language(request, dict(await request.form()))

    def _language(request: Request, form: dict[str, Any]) -> RedirectResponse:
        chosen = str(form.get("language", ""))
        target = local_path(str(form.get("next", "/")))
        response = RedirectResponse(target, status_code=303)
        admin = str(form.get("scope", "")) == "admin"  # the admin panel's language, or the site's
        offered = nest.admin_languages if admin else nest.site_languages
        if chosen in offered:
            response.set_cookie(
                ADMIN_LOCALE_COOKIE if admin else LOCALE_COOKIE,
                chosen,
                max_age=365 * 86400,
                samesite="lax",
                secure=nest.production,
                path="/",
            )
        return response

    @app.get("/_nest/events", include_in_schema=False)
    async def events(request: Request, topic: list[str] = Query(default=[])) -> Any:
        refusal = await nest.broker.allowed(request, topic)
        if refusal is not None:
            status, reason = refusal
            return JSONResponse({"detail": reason}, status_code=status)
        return StreamingResponse(
            nest.broker.stream(request, topic),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )


def _error_page(request: Request, nest: Nest, exc: StarletteHTTPException) -> Response:
    """An HTML page for a browser (the theme's error.html), JSON for anything else."""
    headers = getattr(exc, "headers", None) or {}
    wants_html = "text/html" in request.headers.get("accept", "") and not is_htmx(request)
    if wants_html and exc.status_code >= 400:
        try:
            template = nest.templates.get_template("error.html")
        except TemplateNotFound:
            template = None
        if template is not None:
            try:
                body = template.render(
                    {
                        **nest.template_context(request),
                        "status": exc.status_code,
                        "detail": exc.detail,
                    }
                )
                return HTMLResponse(body, status_code=exc.status_code, headers=headers)
            except Exception:  # noqa: BLE001 - an error page must never fail
                log.exception("error.html failed to render")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


def app_from_env() -> Reloadable:
    """The factory ``nest run``, nest serve's workers and the engine hand uvicorn."""
    app_dir = os.environ.get("NEST_APP_DIR")
    if not app_dir:
        raise HostError("NEST_APP_DIR is not set")
    return Reloadable(lambda: create_app(app_dir))


class Reloadable:
    """The application, made again in place when its modules change (``nest run``, where no
    master reloads workers): the new one is made and started beside the old, then takes
    the next requests, and the old one is stopped. A request already under way finishes
    on the application it began on."""

    def __init__(self, factory: Callable[[], FastAPI]):
        self.factory = factory
        self.app = self._make()
        self._running: Any = None
        self._lock = asyncio.Lock()

    def _make(self) -> FastAPI:
        app = self.factory()
        app.state.nest.reloader = self
        return app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        while True:  # the server's own start and stop
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    self._running = self.app.router.lifespan_context(self.app)
                    await self._running.__aenter__()
                except Exception as e:  # noqa: BLE001 - told to the server, which stops
                    await send({"type": "lifespan.startup.failed", "message": str(e)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._running is not None:
                    await self._running.__aexit__(None, None, None)
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def reload(self) -> None:
        """Make the application again (its workspace's composition, as it is now)."""
        async with self._lock:
            new = await run_in_threadpool(self._make)
            running = new.router.lifespan_context(new)
            await running.__aenter__()
            old, self.app, self._running, old_running = self.app, new, running, self._running
            log.info("%s: made again with its modules as they are now", old.state.nest.name)
            if old_running is not None:
                await old_running.__aexit__(None, None, None)
