"""The ``nest`` command.

nest validate [PATH ...]      every module.yml under PATH, against its contract
nest catalog [APP]            the packages Nest can see
nest plan APP                 what APP is made of, in start order, and its bindings
nest run APP [--port N]       serve APP (development: --reload)
nest new module|app NAME      scaffold a package
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import entry_points
from pathlib import Path

from nest.catalog import Catalog, Entry
from nest.contract import load_contracts
from nest.manifest import MANIFEST_FILE, ManifestError, load_manifest
from nest.resolve import PlanError, plan

SKIP = {".venv", "node_modules", ".git", "build", "dist", "__pycache__", ".pytest_cache"}


def _manifests(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for base in paths:
        if base.is_file():
            found.append(base)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP)
            if MANIFEST_FILE in filenames:
                found.append(Path(dirpath) / MANIFEST_FILE)
    return found


def cmd_validate(args: argparse.Namespace) -> int:
    contract = load_contracts()
    failures = 0
    files = _manifests([Path(p) for p in args.paths or ["."]])
    for path in files:
        try:
            manifest = load_manifest(path)
        except ManifestError as e:
            failures += 1
            print(f"✗ {e}")
            continue
        problems = contract.validate(manifest)
        if problems:
            failures += 1
            print(f"✗ {path}:\n  - " + "\n  - ".join(problems))
        else:
            print(f"✓ {manifest.id} {manifest.module.version} ({manifest.type})  {path}")
    print(f"\n{len(files)} manifests, {failures} with problems")
    if args.strict:
        from nest.boundaries import check  # noqa: PLC0415

        entries = []
        for path in files:
            try:
                entries.append(Entry(manifest=load_manifest(path), source="local"))
            except ManifestError:
                continue
        known = [*Catalog.discover(None), *entries]
        findings = check(entries, known)
        errors = [f for f in findings if f.level == "error"]
        for f in findings:
            print(f)
        print(f"boundaries: {len(errors)} errors, {len(findings) - len(errors)} warnings")
        failures += len(errors)
    return 1 if failures else 0


def cmd_catalog(args: argparse.Namespace) -> int:
    catalog = Catalog.discover(Path(args.app) if args.app else None)
    for entry in catalog:
        print(
            f"{entry.name:24} {entry.manifest.module.version:10} {entry.type:12} {entry.id}  [{entry.source}]"
        )
    for problem in catalog.problems:
        print(f"! {problem}")
    return 1 if catalog.problems else 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.app).resolve()
    try:
        app = Entry(manifest=load_manifest(root), source="application")
        the_plan = plan(app, Catalog.discover(root), load_contracts())
    except (ManifestError, PlanError) as e:
        print(f"✗ {e}")
        return 1
    print(f"{app.name} {app.manifest.module.version}: start order")
    for i, unit in enumerate(the_plan.units, 1):
        route = (unit.instance.route if unit.instance else None) or "-"
        print(f"  {i:2}. {unit.name:24} {unit.entry.type:10} {route}")
    if the_plan.bindings:
        print("bindings")
        for iface, binding in the_plan.bindings.items():
            print(f"  {iface} → {', '.join(binding.providers)}")
    for note in the_plan.notes:
        print(f"note: {note}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    root = Path(args.app).resolve()
    manifest = load_manifest(root)
    port = args.port or (manifest.application.port if manifest.application else None) or 8000
    os.environ["NEST_APP_DIR"] = str(root)
    # Behind a proxy (Caddy, nginx, an ingress), the client's address and scheme come from
    # its X-Forwarded-* headers, believed only from the proxies named here.
    proxies = args.forwarded_allow_ips or os.environ.get("NEST_TRUSTED_PROXIES", "")
    uvicorn.run(
        "nest.host:app_from_env",
        factory=True,
        host=args.host,
        port=port,
        reload=args.reload,
        reload_dirs=[str(root), *(args.watch or [])] if args.reload else None,
        workers=None if args.reload else args.workers,
        proxy_headers=bool(proxies),
        forwarded_allow_ips=proxies or None,
        server_header=False,
        log_level=args.log_level,
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """gunicorn's master and its workers: an application in production."""
    from nest.serve import (  # noqa: PLC0415  # noqa: PLC0415
        EngineProcess,
        ServeError,
        engine_socket,
        gunicorn_options,
        one_process_modules,
        plan,
        preflight,
        process_local_providers,
        run,
        unrelayed_modules,
    )

    root = Path(args.app).resolve()
    os.environ["NEST_APP_DIR"] = str(root)
    environ = {**os.environ}
    try:
        nest = preflight(root, environ)  # migrations and checks, once, before any fork
        the_plan = plan(
            root,
            nest.manifest,
            environ,
            {
                "host": args.host,
                "port": args.port,
                "workers": args.workers,
                "threads": args.threads,
                "timeout": args.timeout,
                "max_requests": args.max_requests,
                "forwarded_allow_ips": args.forwarded_allow_ips,
                "log_level": args.log_level,
            },
            one_process_modules(nest),
            process_local_providers(nest),
            unrelayed_modules(nest),
        )
    except ServeError as e:
        print(f"✗ {e}")
        return 2
    os.environ["NEST_MIGRATE"] = "off"  # done above: the workers do not race at it
    os.environ["NEST_THREADS"] = str(the_plan.threads)
    engine = None
    if the_plan.engine:
        os.environ["NEST_ROLE"] = "web"
        if not os.environ.get("NEST_ENGINE_URL"):  # else an engine runs elsewhere (a service)
            socket = engine_socket(nest.workspace)
            os.environ["NEST_ENGINE_URL"] = f"unix:{socket}"
            if not args.dry_run:
                engine = EngineProcess(root, socket, {**os.environ}, the_plan.log_level)
    for note in the_plan.notes:
        print(f"! {note}")
    print(
        f"nest serve: {the_plan.name} on {the_plan.host}:{the_plan.port}, "
        f"{the_plan.workers} worker{'s' if the_plan.workers != 1 else ''} x {the_plan.threads} threads"
    )
    if args.dry_run:
        for key, value in sorted(gunicorn_options(the_plan).items()):
            print(f"  {key} = {value}")
        return 0
    sys.stdout.flush()  # before the fork: a buffered line would be printed by each worker
    if engine is not None and not engine.start():
        print("✗ the engine process did not start; see its output above")
        engine.stop()
        return 1
    from nest.modules import write_pid  # noqa: PLC0415

    pid_file = write_pid(nest.workspace)  # a module change reloads this master
    try:
        return run(the_plan, on_reload=engine.restart if engine is not None else None)
    finally:
        pid_file.unlink(missing_ok=True)
        if engine is not None:
            engine.stop(the_plan.graceful_timeout + 10)


def cmd_modules(args: argparse.Namespace) -> int:
    """An application's modules: list them, or enable, disable, uninstall one."""
    from nest.modules import ChangeError, change, status  # noqa: PLC0415

    root = Path(args.app).resolve()
    if args.action == "list":
        rows = status(root)
        width = max((len(r.name) for r in rows), default=4)
        for r in rows:
            mark = "🔒" if r.locked else "  "
            extra = []
            if r.needed_by and r.state != "available":
                extra.append("needed by " + ", ".join(r.needed_by))
            if r.data:
                extra.append("keeps data")
            print(
                f"{mark} {r.state:9} {r.name:{width}}  {r.version:8} {r.route or '':14} "
                f"{r.title}" + (f"  ({'; '.join(extra)})" if extra else "")
            )
        return 0
    if not args.name:
        print(f"✗ nest modules {args.action} needs a module's name")
        return 2
    if args.action == "uninstall" and not args.yes:
        print(
            f"Uninstalling {args.name} removes its data and settings (after a backup). "
            "Run again with --yes."
        )
        return 2
    kwargs = {args.action: [args.name]}
    routes = {args.name: args.route} if args.route else None
    try:
        result = change(root, routes=routes, reload=not args.no_reload, say=print, **kwargs)
    except ChangeError as e:
        for problem in e.problems:
            print(f"✗ {problem}")
        return 1
    done = {"enable": "enabled", "disable": "disabled", "uninstall": "uninstalled"}[args.action]
    print(f"✓ {args.name} {done}" + ("; the application is reloading" if result.reloaded else ""))
    for note in result.notes:
        print(f"! {note}")
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    """An application's look: the installed themes, the one it uses; switch."""
    from nest.themes import ThemeError, themes, use  # noqa: PLC0415

    root = Path(args.app).resolve()
    if args.action == "list":
        for t in themes(root):
            mark = "●" if t.active else " "
            extra = (f"  (extends {t.extends})" if t.extends else "") + (
                "  [module.yml]" if t.default else ""
            )
            print(f"{mark} {t.name:14} {t.version:8} {t.title}{extra}")
        return 0
    try:
        notes = use(root, args.name or None)
    except ThemeError as e:
        for problem in e.problems:
            print(f"✗ {problem}")
        return 1
    print(
        f"✓ {args.name or "the manifest's theme"} is the theme now"
        + ("" if notes else "; the application is reloading")
    )
    for note in notes:
        print(f"! {note}")
    return 0


def cmd_packages(args: argparse.Namespace) -> int:
    """The packages this server trusts, installed in an application or not; add, remove."""
    from nest.packages import PackageError, add, remove, status  # noqa: PLC0415

    root = Path(args.app).resolve()
    try:
        if args.action == "list":
            rows = status(root)
            width = max((len(r.offer.name) for r in rows), default=4)
            for r in rows:
                state = "in use" if r.used else ("installed" if r.installed else "available")
                if r.installed and not r.direct and not r.used:
                    state = "with " + ", ".join(r.needed_by[:1])
                if args.installed and not r.installed:
                    continue
                print(
                    f"{state:10} {r.offer.name:{width}}  {r.offer.version:8} {r.offer.type:10} "
                    f"{r.offer.title}" + ("" if r.offer.source == "nest" else "  [registry]")
                )
            return 0
        if not args.name:
            print(f"✗ nest packages {args.action} needs a package's name")
            return 2
        if args.action == "add":
            offer = add(root, args.name)
            if offer.type == "theme":
                print(f"✓ {offer.name} installed: choose it in the admin panel's Themes page, or")
                print(f"  nest themes {args.app} use {offer.name}")
                return 0
            print(f"✓ {offer.name} installed: add it in the admin panel's Modules page, or")
            print(
                f"  nest modules {args.app} enable {offer.name}"
                + ("" if offer.type != "module" else " --route /" + offer.name)
            )
        else:
            remove(root, args.name)
            print(f"✓ {args.name} removed")
    except PackageError as e:
        for problem in e.problems:
            print(f"✗ {problem}")
        return 1
    return 0


def cmd_engine(args: argparse.Namespace) -> int:
    """The engine process: the application with its one-process modules' state, answering
    the workers of nest serve (on a Unix socket, or a port for an engine run as a service)."""
    import uvicorn  # noqa: PLC0415

    root = Path(args.app).resolve()
    os.environ["NEST_APP_DIR"] = str(root)
    os.environ["NEST_ROLE"] = "engine"
    os.environ.pop("NEST_ENGINE_URL", None)
    where: dict[str, object] = (
        {"uds": args.socket} if args.socket else {"host": args.host, "port": args.port}
    )
    uvicorn.run(
        "nest.host:app_from_env",
        factory=True,
        lifespan="on",
        proxy_headers=False,  # the workers say who the visitor is, signed (nest.engine)
        server_header=False,
        log_level=args.log_level,
        timeout_graceful_shutdown=20,
        **where,  # type: ignore[arg-type]
    )
    return 0


def _open(app: str):
    from nest.host import create_app  # noqa: PLC0415

    return create_app(Path(app).resolve(), environ={**os.environ}).state.nest


def cmd_check(args: argparse.Namespace) -> int:
    from nest.ops import check  # noqa: PLC0415

    nest = _open(args.app)
    report = check(nest)
    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    print(f"{nest.name}: ready for production?")
    for f in report.findings:
        print(f"  {marks[f.level]} {f.text}")
    return 1 if report.failed else 0


def cmd_backup(args: argparse.Namespace) -> int:
    from nest.ops import backup  # noqa: PLC0415

    nest = _open(args.app)
    archive = backup(nest, Path(args.to) if args.to else None, keep=args.keep)
    print(f"✓ {archive} ({archive.stat().st_size / 2**20:.1f} MB)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from nest.manifest import load_manifest as _load  # noqa: PLC0415
    from nest.ops import RestoreError, restore  # noqa: PLC0415
    from nest.workspace import resolve_workspace  # noqa: PLC0415

    name = _load(Path(args.app).resolve()).name
    workspace = resolve_workspace(name, os.environ)
    try:
        meta = restore(name, Path(args.archive), workspace, force=args.force)
    except RestoreError as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ {name}: restored the backup of {meta['made']} into {workspace}")
    for missing in meta.get("not_included", []):
        print(f"  not in the backup: {missing}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from nest.scaffold import new_app, new_module

    target = Path(args.into)
    try:
        made = (new_module if args.kind == "module" else new_app)(args.name, target)
    except FileExistsError as e:
        print(f"✗ {e} already exists")
        return 1
    print(f"created {made}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nest", description="Nest: build and run web applications."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check manifests against their contracts")
    p.add_argument("paths", nargs="*")
    p.add_argument(
        "--strict",
        action="store_true",
        help="also check the code keeps to the manifests (boundaries)",
    )
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("catalog", help="list the packages Nest can see")
    p.add_argument("app", nargs="?")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("plan", help="show what an application is made of")
    p.add_argument("app")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="serve an application")
    p.add_argument("app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--watch", action="append", help="another folder to watch with --reload")
    p.add_argument("--log-level", default="info")
    p.add_argument("--workers", type=int, default=1, help="processes (SQLite: keep 1)")
    p.add_argument(
        "--forwarded-allow-ips",
        help="the proxies whose X-Forwarded-* headers are believed (default $NEST_TRUSTED_PROXIES)",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "serve", help="run an application in production: gunicorn's master and workers"
    )
    p.add_argument("app")
    p.add_argument("--host", help="address to listen on (default $NEST_HOST, else 127.0.0.1)")
    p.add_argument("--port", type=int, help="default $PORT, else the application's port")
    p.add_argument("--workers", help="processes, or auto: the CPUs (default serve: workers)")
    p.add_argument("--threads", type=int, help="each worker's threads for synchronous handlers")
    p.add_argument("--timeout", type=int, help="seconds before a silent worker is replaced")
    p.add_argument("--max-requests", type=int, help="requests before a worker is renewed")
    p.add_argument("--forwarded-allow-ips", help="proxies whose X-Forwarded-* are believed")
    p.add_argument("--log-level", help="debug, info, warning, error")
    p.add_argument(
        "--dry-run", action="store_true", help="show the plan and the settings, run nothing"
    )
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("themes", help="an application's look: list the themes, use one")
    p.add_argument("app")
    p.add_argument("action", nargs="?", default="list", choices=["list", "use"])
    p.add_argument("name", nargs="?", help="use: the theme (none: back to module.yml's)")
    p.set_defaults(func=cmd_themes)

    p = sub.add_parser(
        "packages", help="install packages this server trusts into an application, or remove them"
    )
    p.add_argument("app")
    p.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("--installed", action="store_true", help="list: only those installed")
    p.set_defaults(func=cmd_packages)

    p = sub.add_parser("modules", help="an application's modules: list, enable, disable, uninstall")
    p.add_argument("app")
    p.add_argument(
        "action", nargs="?", default="list", choices=["list", "enable", "disable", "uninstall"]
    )
    p.add_argument("name", nargs="?")
    p.add_argument("--route", help="where an added module serves its pages")
    p.add_argument("--yes", action="store_true", help="uninstall: yes, remove its data")
    p.add_argument("--no-reload", action="store_true", help="change it, reload nothing")
    p.set_defaults(func=cmd_modules)

    p = sub.add_parser(
        "engine", help="the engine process: the worlds of a one-process module, for nest serve"
    )
    p.add_argument("app")
    p.add_argument("--socket", help="a Unix socket to listen on (nest serve gives its own)")
    p.add_argument("--host", default="127.0.0.1", help="else this address and --port")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=cmd_engine)

    p = sub.add_parser("check", help="what running an application in production needs")
    p.add_argument("app")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("backup", help="the workspace (databases, files, settings) in one archive")
    p.add_argument("app")
    p.add_argument("--to", help="the folder to write it in (default: the workspace's backups/)")
    p.add_argument("--keep", type=int, default=0, help="keep only the newest N archives there")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="a backup back into the workspace (application stopped)")
    p.add_argument("app")
    p.add_argument("archive")
    p.add_argument("--force", action="store_true", help="over a workspace that holds data")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("new", help="scaffold a module or an application")
    p.add_argument("kind", choices=["module", "app"])
    p.add_argument("name")
    p.add_argument("--into", default=".", help="the folder to create it in")
    p.set_defaults(func=cmd_new)

    # Packages add commands of their own (``nest db ...``) through an entry point:
    # ``[project.entry-points."nest.commands"] db = "nest_db.cli:register"``.
    for ep in sorted(entry_points(group="nest.commands"), key=lambda e: e.name):
        ep.load()(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
