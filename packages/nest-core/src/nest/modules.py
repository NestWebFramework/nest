"""Managing an application's modules: list them, enable, disable, uninstall.

What changes is the workspace's composition (nest.composition); the application is then
made again with it, never patched while it runs:

1. the new composition is planned first: a core module, or one another enabled module
   needs, is refused with the reason, before anything is touched;
2. the workspace is backed up (``backups/``);
3. the application is made with the new composition, which runs the migrations of the
   modules it gained; if that fails, the old composition is put back, and the tables of
   modules enabled just now are taken down again;
4. for an uninstall: the other modules forget what they kept about it (the
   "module.removed" lookup: seo its pages, comments their threads), the packages that keep
   data for others drop its own (the db interface downgrades its migrations to nothing),
   and its settings go;
5. the running application is reloaded: nest serve's workers one by one (the engine
   process with them), so no request is lost. ``nest run`` is restarted by hand.

Enabling and disabling keep a module's data; uninstalling removes it, after the backup.
"""

from __future__ import annotations

import logging
import os
import signal
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest import composition
from nest.catalog import Catalog, Entry
from nest.composition import Choice
from nest.contract import load_contracts
from nest.loader import import_object
from nest.manifest import load_manifest
from nest.resolve import PlanError, plan
from nest.workspace import resolve_workspace

log = logging.getLogger("nest.modules")

MANAGED_TYPES = ("module", "subsystem", "content")
PID_FILE = Path("run") / "serve.pid"
LOG_FILE = Path("data") / "modules.log"


class ChangeError(Exception):
    """A change refused or undone, with every reason."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class ModuleInfo:
    name: str
    type: str
    version: str
    title: str
    description: str
    state: str  # core | enabled | disabled | available
    locked: bool  # core, or needed by a core module or the theme
    route: str | None
    deps: list[str] = field(default_factory=list)  # the managed modules it needs
    needed_by: list[str] = field(default_factory=list)  # the enabled modules that need it
    data: bool = False  # it keeps tables (an uninstall removes them)
    listed: bool = True  # in module.yml (else added from the workspace, or only installed)
    part_of: str | None = None


@dataclass
class Result:
    choices: dict[str, Choice]
    backup: Path | None = None
    reloaded: bool = False
    notes: list[str] = field(default_factory=list)


# --- reading -----------------------------------------------------------------------------


def _context(app_dir: Path, environ: Mapping[str, str]) -> tuple[Any, Path, Catalog]:
    manifest = load_manifest(app_dir)
    workspace = resolve_workspace(manifest.name, dict(environ))
    return manifest, workspace, Catalog.discover(app_dir)


def _plan(manifest: Any, catalog: Catalog, choices: dict[str, Choice]) -> Any:
    composed = manifest.model_copy(update={"modules": composition.compose(manifest, choices)})
    return plan(Entry(manifest=composed, source="application"), catalog, load_contracts())


def _has_data(entry: Entry) -> bool:
    section = entry.manifest.raw.get("db")
    return isinstance(section, dict) and bool(section.get("migrations"))


def status(app_dir: str | Path, environ: Mapping[str, str] | None = None) -> list[ModuleInfo]:
    """Every module the application runs, lists, or could add (installed, not listed)."""
    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    manifest, workspace, catalog = _context(app_dir, environ)
    choices = composition.load(workspace)
    the_plan = _plan(manifest, catalog, choices)
    running = {u.name: u for u in the_plan.units}
    composed = {i.name: i for i in composition.compose(manifest, choices)}
    needed_by: dict[str, set[str]] = {}
    for u in the_plan.units:
        for dep in u.entry.manifest.deps:
            needed_by.setdefault(dep, set()).add(u.name)
    names = list(composed) + sorted(
        e.name
        for e in catalog
        if e.type == "module" and e.name not in composed and e.name not in running
    )
    out = []
    for name in names:
        entry, _ = catalog.find(name)
        if entry is None or entry.type not in MANAGED_TYPES:
            continue
        inst = composed.get(name)
        if inst is None:
            state = "available"
        elif inst.core:
            state = "core"
        else:
            state = "enabled" if name in running else "disabled"
        m = entry.manifest
        out.append(
            ModuleInfo(
                name=name,
                type=entry.type,
                version=m.module.version,
                title=m.module.title or name,
                description=" ".join((m.module.description or "").split()),
                state=state,
                locked=name in the_plan.locked,
                route=inst.route if inst is not None else None,
                deps=sorted(
                    d
                    for d in m.deps
                    if (catalog.find(d)[0] or entry).type in MANAGED_TYPES and d != name
                ),
                needed_by=sorted(needed_by.get(name, set()) - {name}),
                data=_has_data(entry),
                listed=inst is not None and not inst.added,
                part_of=m.part_of,
            )
        )
    return out


# --- changing ----------------------------------------------------------------------------


def change(
    app_dir: str | Path,
    environ: Mapping[str, str] | None = None,
    *,
    enable: Iterable[str] = (),
    disable: Iterable[str] = (),
    uninstall: Iterable[str] = (),
    routes: Mapping[str, str] | None = None,
    reload: bool = True,
    say: Callable[[str], None] = log.info,
    who: str = "",
) -> Result:
    """Enable, disable or uninstall modules, as one change (see the module's doc). Each
    change, done or refused, is written in the workspace's ``data/modules.log``."""
    asked = {"enable": list(enable), "disable": list(disable), "uninstall": list(uninstall)}
    workspace = resolve_workspace(
        load_manifest(Path(app_dir).resolve()).name,
        dict(os.environ if environ is None else environ),
    )
    try:
        result = _change(app_dir, environ, enable, disable, uninstall, routes, reload, say)
    except ChangeError as e:
        _record(workspace, who, asked, "refused", e.problems)
        raise
    _record(workspace, who, asked, "done", [str(result.backup)] if result.backup else [])
    return result


def _record(
    workspace: Path, who: str, asked: dict[str, list[str]], outcome: str, details: list[str]
) -> None:
    import json  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    entry = {
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "who": who,
        **{k: v for k, v in asked.items() if v},
        "outcome": outcome,
        "details": details,
    }
    path = workspace / LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def history(workspace: Path, last: int = 20) -> list[dict[str, Any]]:
    """The latest changes, newest first."""
    import json  # noqa: PLC0415

    path = workspace / LOG_FILE
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-last:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[::-1]


def _change(
    app_dir: str | Path,
    environ: Mapping[str, str] | None,
    enable: Iterable[str],
    disable: Iterable[str],
    uninstall: Iterable[str],
    routes: Mapping[str, str] | None,
    reload: bool,
    say: Callable[[str], None],
) -> Result:
    from nest.host import close_providers, create_app  # noqa: PLC0415
    from nest.ops import backup  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    manifest, workspace, catalog = _context(app_dir, environ)
    enable, disable, uninstall = list(enable), list(disable), list(uninstall)
    routes = dict(routes or {})
    before = composition.load(workspace)
    after = {k: Choice(v.enabled, v.route, dict(v.config)) for k, v in before.items()}
    listed = {i.name: i for i in manifest.modules}
    problems: list[str] = []

    for name in [*enable, *disable, *uninstall]:
        entry, _ = catalog.find(name)
        if entry is None:
            problems.append(f"no package '{name}' is installed")
        elif entry.type not in MANAGED_TYPES:
            problems.append(f"'{name}' is a {entry.type}; only modules are managed here")
        elif entry.manifest.part_of:
            # a game's subsystems are managed once their manifests name every subsystem
            # they rely on (today some only find out at run time)
            problems.append(
                f"{name} is part of {entry.manifest.part_of}; its parts are not managed here yet"
            )
        elif name in listed and listed[name].core and name not in enable:
            problems.append(f"{name} is a core module of {manifest.name}")
    if problems:
        raise ChangeError(problems)

    for name in enable:
        route = routes.get(name) or (after[name].route if name in after else None)
        if name not in listed and not route and _needs_route(catalog.find(name)[0]):
            problems.append(f"{name} serves pages: give it a route (--route /{name})")
        after[name] = Choice(True, route, after[name].config if name in after else {})
    for name in [*disable, *uninstall]:
        if name in listed:
            after[name] = Choice(False, after[name].route if name in after else None)
        else:
            after.pop(name, None)  # added from the workspace: gone from it
    if problems:
        raise ChangeError(problems)

    current = _plan(manifest, catalog, before)
    try:
        target = _plan(manifest, catalog, after)
    except (PlanError, composition.CompositionError) as e:
        raise ChangeError(getattr(e, "problems", [str(e)])) from None
    locked = [n for n in [*disable, *uninstall] if n in current.locked]
    if locked:
        raise ChangeError([f"{n} is needed by a core module or the theme" for n in locked])

    # the backup, from the application as it is
    env_now = {**environ, "NEST_MIGRATE": "off"}
    nest_now = create_app(app_dir, environ=env_now).state.nest
    try:
        archive = backup(nest_now, keep=0)
        say(f"backed up to {archive}")
        revisions_before = _revisions(nest_now, catalog, enable)
    finally:
        close_providers(nest_now)

    composition.save(workspace, after)
    gained = [n for n in enable if n not in {u.name for u in current.units}]
    try:  # made with the new composition: the gained modules' migrations run here
        nest_new = create_app(app_dir, environ={**environ, "NEST_MIGRATE": "auto"}).state.nest
    except Exception as e:
        composition.save(workspace, before)
        _take_down(app_dir, environ, catalog, gained, revisions_before)
        raise ChangeError([f"the application does not start that way: {e}"]) from e
    try:
        for name in uninstall:
            entry, _ = catalog.find(name)
            assert entry is not None
            nest_new.gather("module.removed", name)  # the others forget it
            for unit in nest_new.plan.units:  # the packages keeping data for others drop its
                hook = unit.entry.manifest.forget
                if hook:
                    import_object(hook, unit.entry)(nest_new, entry)
            nest_new.settings.forget(name)
            say(f"uninstalled {name}: its data and settings are gone")
    finally:
        close_providers(nest_new)

    result = Result(choices=after, backup=archive)
    result.notes += [f"note: {n}" for n in target.notes]
    if reload:
        result.reloaded = reload_running(workspace)
        if not result.reloaded:
            result.notes.append("restart the application to apply it (it is not run by nest serve)")
    return result


def _needs_route(entry: Entry | None) -> bool:
    if entry is None or entry.type != "module":
        return False
    raw = entry.manifest.raw
    return "admin" not in raw and raw.get("pages", True) is not False


def _revisions(nest: Any, catalog: Catalog, names: list[str]) -> dict[str, set[str]]:
    """Where each module's migrations stand now (to take a failed enable back)."""
    try:
        from nest_db import migrate  # noqa: PLC0415
    except ImportError:
        return {}
    db = nest.bindings.by_interface.get("nest.db")
    if not db:
        return {}
    out = {}
    for name in names:
        entry, _ = catalog.find(name)
        m = migrate.for_entry(entry) if entry is not None else None
        if m is not None:
            out[name] = migrate.current(db[0].impl, m)
    return out


def _take_down(
    app_dir: Path,
    environ: dict[str, str],
    catalog: Catalog,
    gained: list[str],
    before: dict[str, set[str]],
) -> None:
    """After a failed enable: the tables of modules that had none before go again."""
    from nest.host import close_providers, create_app  # noqa: PLC0415

    fresh = [n for n in gained if not before.get(n)]
    if not fresh:
        return
    try:
        from nest_db import migrate  # noqa: PLC0415

        nest = create_app(app_dir, environ={**environ, "NEST_MIGRATE": "off"}).state.nest
    except Exception:  # noqa: BLE001 - the backup is there for the worst case
        log.exception("could not take the failed modules' tables down")
        return
    try:
        for name in fresh:
            entry, _ = catalog.find(name)
            if entry is not None:
                migrate.on_forget(nest, entry)  # its tables and its version table
    finally:
        close_providers(nest)


# --- reloading -----------------------------------------------------------------------------


def write_pid(workspace: Path) -> Path:
    """nest serve's master says where it is, so a change can reload it."""
    path = workspace / PID_FILE
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    return path


def reload_app(nest: Any) -> str:
    """Apply a change to the running application: nest serve's workers reloaded ("serve"),
    or, under nest run, the application made again in place ("process", soon after this
    returns, so the request asking finishes first); "" when neither can be done."""
    if reload_running(nest.workspace):
        return "serve"
    reloader = getattr(nest, "reloader", None)
    if reloader is None:
        return ""
    import asyncio  # noqa: PLC0415

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return ""
    loop.call_later(0.3, lambda: asyncio.ensure_future(reloader.reload()))
    return "process"


def reload_running(workspace: Path) -> bool:
    """HUP to the nest serve master of this workspace, if one runs: its workers are made
    again one by one, with the engine process. False when none runs."""
    path = workspace / PID_FILE
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes() if Path("/proc").is_dir() else b"nest"
    except (OSError, ValueError):
        return False
    if b"nest" not in cmdline:  # a pid reused by something else
        return False
    try:
        os.kill(pid, signal.SIGHUP)
    except OSError:
        return False
    return True
