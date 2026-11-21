"""``nest comments``: moving comments in.

nest comments import-wordpress APP DUMP.sql   (after the posts: nest content import-wordpress)
nest comments import-glossword APP DUMP.sql   (after the terms: nest glossary import-glossword-db)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any


def _wordpress(args: argparse.Namespace) -> int:
    from nest.host import create_app
    from nest_comments.wordpress import import_dump

    nest = create_app(args.app, environ={**os.environ}).state.nest
    report = import_dump(
        nest.bindings.get("nest.db"), nest.lookup, Path(args.dump), prefix=args.prefix
    )
    print(
        f"✓ {report.comments} comments"
        + (f", {report.skipped} left (trash, pingbacks)" if report.skipped else "")
    )
    if report.orphans:
        print(f"  ! {len(report.orphans)} comments belong to posts that were not moved")
    return 0


def _glossword(args: argparse.Namespace) -> int:
    from nest.host import create_app
    from nest_comments.glossword import import_dump

    nest = create_app(args.app, environ={**os.environ}).state.nest
    report = import_dump(
        nest.bindings.get("nest.db"), nest.lookup, Path(args.dump), prefix=args.prefix
    )
    print(f"✓ {report.comments} comments" + (f", {report.skipped} left" if report.skipped else ""))
    if report.orphans:
        print(f"  ! {len(report.orphans)} comments belong to terms that were not moved")
    return 0


def register(sub: Any) -> None:
    c = sub.add_parser("comments", help="comments")
    actions = c.add_subparsers(dest="comments_command", required=True)
    p = actions.add_parser("import-wordpress", help="move a WordPress site's comments in")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--prefix", default="wp_")
    p.set_defaults(func=_wordpress)
    p = actions.add_parser(
        "import-glossword", help="move a Glossword site's comments in (GentleSource)"
    )
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--prefix", default="cmt_")
    p.set_defaults(func=_glossword)
