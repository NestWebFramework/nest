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
    from nest.serve import ServeError, gunicorn_options, one_process_modules, plan, preflight, run  # noqa: PLC0415

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
        )
    except ServeError as e:
        print(f"✗ {e}")
        return 2
    os.environ["NEST_MIGRATE"] = "off"  # done above: the workers do not race at it
    os.environ["NEST_THREADS"] = str(the_plan.threads)
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
    return run(the_plan)


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
