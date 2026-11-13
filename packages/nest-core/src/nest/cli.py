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
        route = unit.instance.route if unit.instance else "-"
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
    uvicorn.run(
        "nest.host:app_from_env",
        factory=True,
        host=args.host,
        port=port,
        reload=args.reload,
        reload_dirs=[str(root), *(args.watch or [])] if args.reload else None,
        log_level=args.log_level,
    )
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
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("new", help="scaffold a module or an application")
    p.add_argument("kind", choices=["module", "app"])
    p.add_argument("name")
    p.add_argument("--into", default=".", help="the folder to create it in")
    p.set_defaults(func=cmd_new)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
