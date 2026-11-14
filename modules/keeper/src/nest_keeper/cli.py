"""``nest keeper``: the keeper's API tokens from the command line.

nest keeper token APP NAME     make a token (printed once; keep it safe)
nest keeper tokens APP         list them (never the secrets)
nest keeper revoke APP ID      revoke one
"""

from __future__ import annotations

import argparse
import os
from typing import Any


def _db(app: str) -> Any:
    from nest.host import create_app

    return create_app(app, environ={**os.environ}).state.nest.bindings.get("nest.db")


def _token(args: argparse.Namespace) -> int:
    from nest_keeper import tokens

    try:
        secret, t = tokens.create(_db(args.app), args.name)
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ token #{t.id} {t.name} (scopes: {', '.join(t.scopes)}); shown this once:\n{secret}")
    return 0


def _tokens(args: argparse.Namespace) -> int:
    from nest_keeper import tokens

    for t in tokens.listing(_db(args.app)):
        state = "revoked" if t.revoked else f"last used {t.last_used_at or 'never'}"
        print(f"#{t.id:<4} {t.prefix}…  {t.name:30} {state}")
    return 0


def _revoke(args: argparse.Namespace) -> int:
    from nest_keeper import tokens

    if not tokens.revoke(_db(args.app), args.id):
        print("✗ no such token")
        return 1
    print(f"✓ token #{args.id} revoked")
    return 0


def register(sub: Any) -> None:
    keeper = sub.add_parser("keeper", help="the keeper's API tokens")
    actions = keeper.add_subparsers(dest="keeper_command", required=True)
    p = actions.add_parser("token", help="make an API token (printed once)")
    p.add_argument("app")
    p.add_argument("name")
    p.set_defaults(func=_token)
    p = actions.add_parser("tokens", help="list the API tokens")
    p.add_argument("app")
    p.set_defaults(func=_tokens)
    p = actions.add_parser("revoke", help="revoke an API token")
    p.add_argument("app")
    p.add_argument("id", type=int)
    p.set_defaults(func=_revoke)
