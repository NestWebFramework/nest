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
import inspect
import logging
import os
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

from nest.bind import Bindings, ProviderContext, build
from nest.catalog import Catalog, Entry
from nest.contract import load_contracts
from nest.i18n import LOCALE_COOKIE, Catalogs, LocaleMiddleware, translator
from nest.loader import import_main, import_object
from nest.manifest import load_manifest
from nest.realtime import Broker, Topic
from nest.resolve import Plan, Unit, plan
from nest.security import CSRF_FIELD, SecurityMiddleware, csrf_protect, local_path
from nest.settings import Namespaced, SettingsStore
from nest.shortcodes import Shortcodes
from nest.templating import is_htmx, make_environment, render_block
from nest.workspace import environment, is_production, resolve_workspace, secret_key

log = logging.getLogger("nest")

Hook = Callable[[], Any | Awaitable[Any]]


class HostError(Exception):
    pass


@dataclass
class ModuleState:
    name: str
    type: str
    version: str
    route: str | None
    state: str = "pending"
    reason: str | None = None


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
        self.app: FastAPI | None = None
        self._context: list[Callable[[Request], Mapping[str, Any]]] = []
        self._fallbacks: list[tuple[str, Callable[[Request], Any]]] = []
        self._middleware: list[tuple[type, dict[str, Any]]] = []
        self._startup: list[Hook] = []
        self._shutdown: list[Hook] = []
        self._background: list[Callable[[], Awaitable[Any]]] = []
        self._versions = {u.name: u.entry.manifest.module.version for u in plan.units}
        module_dirs: dict[str, Path] = {}
        for unit in plan.units:
            folder = unit.entry.manifest.folder(unit.entry.manifest.templates, "templates")
            if folder is not None and unit.entry is not plan.theme:
                module_dirs[unit.name] = folder
        theme_dir = None
        if plan.theme is not None:
            theme_dir = plan.theme.manifest.folder(plan.theme.manifest.templates, "templates")
        self.templates = make_environment(plan.app.root, theme_dir, module_dirs)
        languages = application.languages if application else ["en"]
        default = (application.default_language if application else None) or languages[0]
        self.catalogs = Catalogs(languages, default)
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
        )

    def asset(self, module: str, path: str) -> str:
        """The URL of a module's static file, versioned so caches can keep it."""
        if module not in self._versions:
            raise LookupError(f"no module '{module}' in this application")
        return f"/assets/{module}/{path}?v={self._versions[module]}"

    def template_context(self, request: Request) -> dict[str, Any]:
        token = request.state.csrf_token
        field = Markup(f'<input type="hidden" name="{CSRF_FIELD}" value="{escape(token)}">')
        context: dict[str, Any] = {}
        for provide in self._context:
            context.update(provide(request))
        t = translator(request)
        context.update(
            request=request,
            csrf_token=token,
            csrf_field=field,
            is_htmx=is_htmx(request),
            _=t.gettext,
            ngettext=t.ngettext,
            locale=t.locale,
        )
        return context

    def render_block(self, name: str, block: str, **context: Any) -> str:
        """A fragment rendered outside a request, for an SSE event."""
        return render_block(self.templates, name, block, context)

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI):
        for hook in self._startup:
            await _maybe(hook())
        tasks = [
            asyncio.create_task(fn(), name=getattr(fn, "__name__", "task"))
            for fn in self._background
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


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class ModuleRealtime:
    """A module's view of the broker: it registers and publishes its own topics."""

    def __init__(self, broker: Broker, owner: str):
        self._broker = broker
        self._owner = owner

    def topic(self, name: str, **kwargs: Any) -> Topic:
        return self._broker.register(name, self._owner, **kwargs)

    def publish(self, topic: str, event: str, data: str) -> None:
        registered = self._broker.topics.get(topic)
        if registered is not None and registered.owner != self._owner:
            raise HostError(
                f"{self._owner} cannot publish to '{topic}', which {registered.owner} owns"
            )
        self._broker.publish(topic, event, data)

    def subscribers(self, topic: str) -> int:
        return self._broker.subscribers(topic)


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

    def mount(self, router: APIRouter) -> None:
        """Serve ``router`` at the route the application chose for this module."""
        if self.route is None:
            raise HostError(f"{self.name} has no route; an application must include it with one")
        prefix = "" if self.route == "/" else self.route
        assert self._nest.app is not None
        self._nest.app.include_router(router, prefix=prefix, dependencies=[Depends(csrf_protect)])

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

    def background(self, fn: Callable[[], Awaitable[Any]]) -> Callable[[], Awaitable[Any]]:
        """A task that runs from startup until shutdown."""
        self._nest._background.append(fn)
        return fn

    @property
    def state(self) -> dict[str, Any]:
        """This module's run-time state in this application (instead of globals)."""
        return self._nest.module_state.setdefault(self.name, {})

    def context(self, fn: Callable[[Request], Mapping[str, Any]]) -> Callable:
        """Add values to every page's template context (``user``, for the auth module)."""
        self._nest._context.append(fn)
        return fn

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

    def fallback(self, fn: Callable[[Request], Any]) -> Callable[[Request], Any]:
        """Answer a GET that no route matched: return a response, or None to pass it on.

        Fallbacks are asked in start order. This is how a module serves paths it
        stores rather than declares (a CMS page at /history/the-church/) without
        a catch-all route that would shadow every module mounted after it. A
        blocking fallback is run in the thread pool.
        """
        self._nest._fallbacks.append((self.name, fn))
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


def module_state(request: Request, module: str) -> dict[str, Any]:
    """A module's run-time state, from a request (for dependencies a module exports)."""
    return request.app.state.nest.module_state.setdefault(module, {})


def create_app(app_dir: str | Path, *, environ: Mapping[str, str] | None = None) -> FastAPI:
    app_root = Path(app_dir).resolve()
    manifest = load_manifest(app_root)
    app_entry = Entry(manifest=manifest, source="application")
    catalog = Catalog.discover(app_root)
    for problem in catalog.problems:
        log.warning("catalog: %s", problem)
    the_plan = plan(app_entry, catalog, load_contracts())
    for note in the_plan.notes:
        log.warning("%s", note)

    base_env = dict(os.environ if environ is None else environ)
    workspace = resolve_workspace(manifest.name, base_env)
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
                f"/assets/{unit.name}", StaticFiles(directory=static), name=f"assets:{unit.name}"
            )
        if entry.type in ("module", "theme"):
            nest.settings.declare(
                unit.name, entry.manifest.settings, unit.instance.config if unit.instance else None
            )
            _setup(nest, unit)
        else:
            nest.states[unit.name].state = "ready"

    for cls, options in nest._middleware:
        app.add_middleware(cls, **options)
    app.add_middleware(LocaleMiddleware, catalogs=nest.catalogs)
    # Added last, so outermost: every response gets the headers, whatever a module did.
    app.add_middleware(SecurityMiddleware, secret=nest.secret, secure_cookies=nest.production)
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
            state.state, state.reason = "degraded", f"{type(e).__name__}: {e}"
            log.exception("%s failed to set up; it is optional and starts degraded", unit.name)
            return
        raise HostError(f"{unit.name} failed to set up: {type(e).__name__}: {e}") from e


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
            for owner, fn in nest._fallbacks:
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

    @app.post("/_nest/language", include_in_schema=False, dependencies=[Depends(csrf_protect)])
    async def choose_language(request: Request) -> RedirectResponse:
        form = await request.form()
        chosen = str(form.get("language", ""))
        target = local_path(str(form.get("next", "/")))
        response = RedirectResponse(target, status_code=303)
        if chosen in nest.catalogs.languages:
            response.set_cookie(
                LOCALE_COOKIE,
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


def app_from_env() -> FastAPI:
    """The factory ``nest run`` hands uvicorn, so reload rebuilds the whole app."""
    app_dir = os.environ.get("NEST_APP_DIR")
    if not app_dir:
        raise HostError("NEST_APP_DIR is not set")
    return create_app(app_dir)
