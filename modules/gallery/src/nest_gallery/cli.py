"""``nest gallery``: galleries from the command line.

nest gallery import-wordpress APP DUMP.sql --uploads WP-CONTENT/uploads [--all]
nest gallery list APP
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any


def _app(app: str) -> Any:
    from nest.host import create_app

    return create_app(app, environ={**os.environ}).state.nest


def _wordpress(args: argparse.Namespace) -> int:
    from nest_gallery.wordpress import import_dump

    nest = _app(args.app)
    report = import_dump(
        nest.bindings.get("nest.db"),
        nest.bindings.get("nest.storage"),
        Path(args.dump),
        uploads=Path(args.uploads),
        prefix=args.prefix,
        everything=args.all,
    )
    print(
        f"✓ {report.galleries} galleries, {report.albums} albums, {report.photos} photos"
        + (
            f"; {report.skipped} galleries no page uses were left (--all moves them)"
            if report.skipped
            else ""
        )
    )
    for path in report.missing[:10]:
        print(f"  ! missing {path}")
    if len(report.missing) > 10:
        print(f"  ! … and {len(report.missing) - 10} more missing files")
    return 0


def _geticus(args: argparse.Namespace) -> int:
    from nest_gallery.geticus import import_dump

    nest = _app(args.app)
    report = import_dump(
        nest.bindings.get("nest.db"),
        nest.bindings.get("nest.storage"),
        Path(args.dump),
        root=Path(args.root),
    )
    print(f"✓ {report.galleries} galleries, {report.photos} photos")
    for path in report.missing[:10]:
        print(f"  ! missing {path}")
    return 0


def _list(args: argparse.Namespace) -> int:
    from nest_gallery import service

    nest = _app(args.app)
    db = nest.bindings.get("nest.db")

    def show(parent: int | None, depth: int) -> None:
        for card in service.cards(db, parent):
            kind = "album" if card.is_album else "gallery"
            print(
                f"{'  ' * depth}{card.collection.slug:40} {kind:8} {card.count:5}  {card.collection.title}"
            )
            show(card.collection.id, depth + 1)

    show(None, 0)
    return 0


def register(sub: Any) -> None:
    g = sub.add_parser("gallery", help="photo galleries and albums")
    actions = g.add_subparsers(dest="gallery_command", required=True)
    p = actions.add_parser("import-wordpress", help="move Photo Gallery and NextGEN galleries in")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--uploads", required=True, help="the site's wp-content/uploads folder")
    p.add_argument("--prefix", default="wp_")
    p.add_argument("--all", action="store_true", help="every gallery, not only those a page uses")
    p.set_defaults(func=_wordpress)
    p = actions.add_parser("import-geticus", help="move a Geticus site's galleries in")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--root", required=True, help="the site's folder (where assets/ is)")
    p.set_defaults(func=_geticus)
    p = actions.add_parser("list", help="the albums and galleries")
    p.add_argument("app")
    p.set_defaults(func=_list)
