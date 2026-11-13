"""``nest auth``: accounts from the command line.

nest auth create-user APP EMAIL [--name NAME] [--role admin] [--password-stdin]
nest auth sign-out-everywhere APP EMAIL
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Any

from sqlalchemy import select


def _db(app: str) -> Any:
    from nest.host import create_app

    nest = create_app(app, environ={**os.environ}).state.nest
    return nest, nest.bindings.get("nest.db")


def _create(args: argparse.Namespace) -> int:
    from nest_auth.sessions import AccountError, create_user

    nest, db = _db(args.app)
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Again: ") != password:
            print("✗ the passwords differ")
            return 1
    try:
        user = create_user(
            db,
            args.email,
            password,
            name=args.name or "",
            roles=tuple(args.role or ()),
            min_length=int(nest.settings.get("auth.min_password_length")),
        )
    except AccountError as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ {user.email} (roles: {', '.join(sorted(user.roles)) or 'none'})")
    return 0


def _sign_out(args: argparse.Namespace) -> int:
    from nest_auth.models import User
    from nest_auth.sessions import close_all_sessions, normalize_email

    _nest, db = _db(args.app)
    with db.session() as s:
        user_id = s.scalar(select(User.id).where(User.email == normalize_email(args.email)))
    if user_id is None:
        print("✗ no such account")
        return 1
    close_all_sessions(db, user_id)
    print("✓ every session of that account has ended")
    return 0


def register(sub: Any) -> None:
    auth = sub.add_parser("auth", help="accounts")
    actions = auth.add_subparsers(dest="auth_command", required=True)

    p = actions.add_parser("create-user", help="create an account")
    p.add_argument("app")
    p.add_argument("email")
    p.add_argument("--name")
    p.add_argument("--role", action="append", help="a role; repeat for several (admin has all)")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    p.set_defaults(func=_create)

    p = actions.add_parser("sign-out-everywhere", help="end every session of an account")
    p.add_argument("app")
    p.add_argument("email")
    p.set_defaults(func=_sign_out)
