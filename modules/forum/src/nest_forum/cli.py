"""``nest forum``: boards from the command line.

nest forum add-board APP TITLE [--description D] [--slug S]
nest forum boards APP
"""

from __future__ import annotations

import argparse
import os
from typing import Any


def _db(app: str) -> Any:
    from nest.host import create_app

    return create_app(app, environ={**os.environ}).state.nest.bindings.get("nest.db")


def _add(args: argparse.Namespace) -> int:
    from nest_forum import service

    b = service.ensure_board(
        _db(args.app), args.title, slug=args.slug or "", description=args.description or ""
    )
    print(f"✓ {b.slug}: {b.title}")
    return 0


def _boards(args: argparse.Namespace) -> int:
    from nest_forum import service

    for r in service.boards(_db(args.app)):
        print(f"{r.board.slug:30} {r.topics:5} topics {r.posts:6} posts  {r.board.title}")
    return 0


def register(sub: Any) -> None:
    f = sub.add_parser("forum", help="the forum's boards")
    actions = f.add_subparsers(dest="forum_command", required=True)
    p = actions.add_parser("add-board", help="add (or rename) a board")
    p.add_argument("app")
    p.add_argument("title")
    p.add_argument("--slug")
    p.add_argument("--description")
    p.set_defaults(func=_add)
    p = actions.add_parser("boards", help="list the boards")
    p.add_argument("app")
    p.set_defaults(func=_boards)
