"""``nest registry``: a registry's own command (its server side)."""

from __future__ import annotations

import argparse
from pathlib import Path


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("registry", help="a Nest registry: make a publish token for an account")
    sp = p.add_subparsers(dest="registry_command", required=True)
    t = sp.add_parser("token", help="a token an account publishes with (shown once)")
    t.add_argument("app")
    t.add_argument("email")
    t.add_argument("--name", default="command line")
    t.set_defaults(func=_token)


def _token(args: argparse.Namespace) -> int:
    from nest_auth import find_user  # noqa: PLC0415

    from nest import create_app  # noqa: PLC0415
    from nest_registry import service  # noqa: PLC0415

    nest = create_app(Path(args.app).resolve()).state.nest
    db = nest.bindings.get("nest.db")
    user = find_user(db, args.email)
    if user is None:
        print(f"✗ no account {args.email}")
        return 1
    secret, _row = service.make_token(db, user.id, args.name)
    print(secret)
    return 0
