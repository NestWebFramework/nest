"""``nest db``: migrations from the command line.

nest db status APP                       each module: applied, pending, or none
nest db upgrade APP [MODULE]             apply what is pending (a cluster runs this as a job)
nest db downgrade APP MODULE TARGET      step a module back (a revision, or -1)
nest db revision APP MODULE -m MESSAGE [--autogenerate]
"""

from __future__ import annotations

import argparse
from typing import Any

from nest_db import migrate


def _nest(app: str) -> Any:
    import os

    from nest.host import create_app

    env = {**os.environ, "NEST_MIGRATE": "off"}
    return create_app(app, environ=env).state.nest


def _modules(nest: Any, only: str | None) -> list[migrate.ModuleMigrations]:
    modules = migrate.discover(nest.plan)
    if only:
        modules = [m for m in modules if m.name == only]
        if not modules:
            raise SystemExit(f"✗ {only} declares no migrations in this application")
    return modules


def _status(args: argparse.Namespace) -> int:
    nest = _nest(args.app)
    db = nest.bindings.get("nest.db")
    print(f"{nest.name} on {db.dialect()}")
    behind = 0
    for m in _modules(nest, None):
        now, want = migrate.current(db, m), migrate.heads(m)
        state = "up to date" if now == want else "pending"
        behind += now != want
        print(
            f"  {m.name:20} {state:11} at {','.join(sorted(now)) or '-'}  head {','.join(sorted(want)) or '-'}"
        )
    return 1 if behind else 0


def _upgrade(args: argparse.Namespace) -> int:
    nest = _nest(args.app)
    db = nest.bindings.get("nest.db")
    for m in _modules(nest, args.module):
        if migrate.pending(db, m):
            migrate.upgrade(db, m)
            print(f"✓ {m.name} upgraded to {','.join(sorted(migrate.current(db, m)))}")
        else:
            print(f"· {m.name} is up to date")
    return 0


def _downgrade(args: argparse.Namespace) -> int:
    nest = _nest(args.app)
    db = nest.bindings.get("nest.db")
    (m,) = _modules(nest, args.module)
    migrate.downgrade(db, m, args.target)
    print(f"✓ {m.name} at {','.join(sorted(migrate.current(db, m))) or 'base'}")
    return 0


def _revision(args: argparse.Namespace) -> int:
    nest = _nest(args.app)
    db = nest.bindings.get("nest.db")
    (m,) = _modules(nest, args.module)
    path = migrate.revision(db, m, args.message, autogenerate=args.autogenerate)
    print(f"✓ wrote {path}")
    return 0


def register(sub: Any) -> None:
    db = sub.add_parser("db", help="database migrations, per module")
    actions = db.add_subparsers(dest="db_command", required=True)

    p = actions.add_parser("status", help="what is applied and what is pending")
    p.add_argument("app")
    p.set_defaults(func=_status)

    p = actions.add_parser("upgrade", help="apply pending migrations")
    p.add_argument("app")
    p.add_argument("module", nargs="?")
    p.set_defaults(func=_upgrade)

    p = actions.add_parser("downgrade", help="step one module back")
    p.add_argument("app")
    p.add_argument("module")
    p.add_argument("target", help="a revision id, or -1")
    p.set_defaults(func=_downgrade)

    p = actions.add_parser("revision", help="write a new migration for a module")
    p.add_argument("app")
    p.add_argument("module")
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--autogenerate", action="store_true", help="from the module's models")
    p.set_defaults(func=_revision)
