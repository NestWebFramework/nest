"""``nest agent token APP [--control]``: a token for the keeper, and the line for the site.

The token goes to the keeper (its Sites page); the line goes to the site's environment
(``/etc/nest/<site>.env`` when deployed with nest-site, the workspace's .env locally).
Neither is stored anywhere by this command.
"""

from __future__ import annotations

import argparse
from typing import Any


def _token(args: argparse.Namespace) -> int:
    from nest.bind import env_name
    from nest.manifest import load_manifest
    from nest_agent import tokens

    try:
        name = load_manifest(args.app).name
    except Exception:  # noqa: BLE001 - an application name given instead of a folder
        name = args.app
    token, kept = tokens.make()
    key = "control_token" if args.control else "read_token"
    print(f"For the keeper ({'reads and acts' if args.control else 'reads'}), shown this once:")
    print(f"  {token}")
    print("For the site's environment:")
    print(f"  {env_name(name, 'agent', key)}={kept}")
    return 0


def register(sub: Any) -> None:
    agent = sub.add_parser("agent", help="the agent's tokens, for the keeper")
    actions = agent.add_subparsers(dest="agent_command", required=True)
    p = actions.add_parser("token", help="make a token (printed once) and the site's line")
    p.add_argument("app", help="the application's folder (or its name)")
    p.add_argument("--control", action="store_true", help="a token that may also run actions")
    p.set_defaults(func=_token)
