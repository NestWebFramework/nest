"""``nest redirects``: managing redirects from the command line.

nest redirects add APP SOURCE TARGET [--status 301]
nest redirects import-csv APP FILE.csv      (source,target[,status] per line)
nest redirects list APP
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any


def _db(app: str) -> Any:
    from nest.host import create_app

    return create_app(app, environ={**os.environ}).state.nest.bindings.get("nest.db")


def _add(args: argparse.Namespace) -> int:
    from nest_redirects import service

    try:
        r = service.add(_db(args.app), args.source, args.target, args.status)
    except service.RedirectError as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ {r.source} → {r.target or '(gone)'} ({r.status})")
    return 0


def _csv(args: argparse.Namespace) -> int:
    from nest_redirects import service

    db = _db(args.app)
    done, failed = 0, 0
    with Path(args.file).open(encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.reader(f), 1):
            if not row or row[0].startswith("#") or row[0].lower() == "source":
                continue
            try:
                service.add(
                    db,
                    row[0],
                    row[1] if len(row) > 1 else "",
                    int(row[2]) if len(row) > 2 and row[2] else 301,
                )
                done += 1
            except (service.RedirectError, ValueError, IndexError) as e:
                failed += 1
                print(f"  ! line {i}: {e}")
    print(f"✓ {done} redirects" + (f", {failed} refused" if failed else ""))
    return 1 if failed else 0


def _list(args: argparse.Namespace) -> int:
    from nest_redirects import service

    for r in service.listing(_db(args.app), limit=100000):
        print(f"{r.status}  {r.source}  →  {r.target}  ({r.hits} hits)")
    return 0


def register(sub: Any) -> None:
    r = sub.add_parser("redirects", help="old addresses sent on to new ones")
    actions = r.add_subparsers(dest="redirects_command", required=True)
    p = actions.add_parser("add", help="add or change a redirect")
    p.add_argument("app")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--status", type=int, default=301)
    p.set_defaults(func=_add)
    p = actions.add_parser("import-csv", help="add redirects from a CSV file")
    p.add_argument("app")
    p.add_argument("file")
    p.set_defaults(func=_csv)
    p = actions.add_parser("list", help="every redirect")
    p.add_argument("app")
    p.set_defaults(func=_list)
