"""``nest docs``: the documentation from the command line.

nest docs check APP     the links and pictures that lead nowhere (exit 1 when some do)
nest docs pages APP     the pages, by section
"""

from __future__ import annotations

import argparse
import os
from typing import Any


def _tree(app: str) -> Any:
    from nest.host import create_app

    nest = create_app(app, environ={**os.environ}).state.nest
    return nest.module_state["docs"]["tree"]


def _check(args: argparse.Namespace) -> int:
    tree = _tree(args.app)
    problems = tree.broken()
    for p in problems:
        print(f"✗ {p}")
    pages = len(tree.all_pages())
    print(f"{'✓' if not problems else '✗'} {pages} pages, {len(problems)} broken links")
    return 1 if problems else 0


def _pages(args: argparse.Namespace) -> int:
    tree = _tree(args.app)
    for s in tree.sections:
        print(s.title)
        for e in s.entries:
            print(f"  {tree.url(e.key):45} {e.title}")
    return 0


def register(sub: Any) -> None:
    d = sub.add_parser("docs", help="the documentation")
    actions = d.add_subparsers(dest="docs_command", required=True)
    p = actions.add_parser("check", help="links and pictures that lead nowhere")
    p.add_argument("app")
    p.set_defaults(func=_check)
    p = actions.add_parser("pages", help="the pages, by section")
    p.add_argument("app")
    p.set_defaults(func=_pages)
