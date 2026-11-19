"""``nest maps``: the maps from the command line.

nest maps list APP
nest maps import-wordpress APP DUMP.sql [--prefix wp_]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any


def _db(app: str) -> Any:
    from nest.host import create_app

    return create_app(app, environ={**os.environ}).state.nest.bindings.get("nest.db")


def _list(args: argparse.Namespace) -> int:
    from nest_maps import service

    for m, count in service.maps(_db(args.app)):
        print(f"{m.slug:30} {count:4} markers  {m.lat:.5f}, {m.lng:.5f} z{m.zoom}  {m.title}")
    return 0


def _wordpress(args: argparse.Namespace) -> int:
    from nest_maps.wordpress import import_dump

    report = import_dump(_db(args.app), Path(args.dump), prefix=args.prefix)
    print(f"✓ {report.maps} maps, {report.markers} markers")
    for line in report.skipped:
        print(f"  skipped: {line}")
    return 0


def register(sub: Any) -> None:
    g = sub.add_parser("maps", help="maps and their markers")
    actions = g.add_subparsers(dest="maps_command", required=True)

    p = actions.add_parser("list", help="list the maps")
    p.add_argument("app")
    p.set_defaults(func=_list)

    p = actions.add_parser("import-wordpress", help="import WP Google Maps from a MySQL dump")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--prefix", default="wp_")
    p.set_defaults(func=_wordpress)
