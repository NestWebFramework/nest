"""``nest content``: moving sites in, and keeping the index true.

nest content import-wordpress APP DUMP.sql [--uploads WP-CONTENT/uploads] [--prefix wp_]
nest content import-joomla APP DUMP.sql --root PUBLIC_HTML [--places loc --place-taxonomy categorie --events efemeride]
nest content reindex APP
nest content types APP
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
    from nest_content.wordpress import import_dump

    nest = _app(args.app)
    b = nest.bindings
    report = import_dump(
        b.get("nest.db"),
        b.get("nest.search"),
        b.get("nest.storage"),
        nest.module_state["content"]["types"],
        Path(args.dump),
        uploads=Path(args.uploads) if args.uploads else None,
        prefix=args.prefix,
        settings=nest.settings,
    )
    print(
        f"✓ {report.terms} terms, {report.entries} entries, {report.media} media "
        f"(+{report.files} files), {report.menus} menus"
    )
    skipped: dict[str, int] = {}
    for s in report.skipped:
        skipped[s.split()[0]] = skipped.get(s.split()[0], 0) + 1
    for kind, n in sorted(skipped.items()):
        print(f"  not moved: {n} × {kind}")
    for w in report.warnings[:20]:
        print(f"  ! {w}")
    if len(report.warnings) > 20:
        print(f"  ! … and {len(report.warnings) - 20} more")
    return 0


def _geticus(args: argparse.Namespace) -> int:
    from nest_content.geticus import import_dump

    nest = _app(args.app)
    b = nest.bindings
    report = import_dump(
        b.get("nest.db"),
        b.get("nest.search"),
        b.get("nest.storage"),
        nest.module_state["content"]["types"],
        Path(args.dump),
        root=Path(args.root) if args.root else None,
        plain_type=args.plain_type,
        categorized_type=args.categorized_type,
        language=args.language,
        settings=nest.settings,
    )
    print(
        f"✓ {report.terms} categories, {report.entries} entries (+{report.files} files), {report.menu_items} menu items"
    )
    for line in report.skipped:
        print(f"  not moved: {line}")
    for path in report.missing[:10]:
        print(f"  ! missing {path}")
    return 0


def _joomla(args: argparse.Namespace) -> int:
    from nest_content.joomla import import_dump

    nest = _app(args.app)
    b = nest.bindings
    report = import_dump(
        b.get("nest.db"),
        b.get("nest.search"),
        b.get("nest.storage"),
        nest.module_state["content"]["types"],
        Path(args.dump),
        root=Path(args.root) if args.root else None,
        prefix=args.prefix,
        article_type=args.type,
        skip=set(args.skip.split(",")) if args.skip else set(),
        place_type=args.places,
        place_taxonomy=args.place_taxonomy,
        skip_place_categories={int(x) for x in args.skip_place_categories.split(",") if x},
        event_type=args.events,
    )
    print(
        f"✓ {report.entries} articles, {report.places} places ({report.terms} categories), "
        f"{report.events} events (+{report.files} files)"
    )
    for line in report.skipped:
        print(f"  not moved: {line}")
    for path in report.missing[:10]:
        print(f"  ! missing {path}")
    return 0


def _reindex(args: argparse.Namespace) -> int:
    from nest_content import service

    nest = _app(args.app)
    registry = nest.module_state["content"][
        "types"
    ]  # every language's index, not only the default's
    done = service.reindex(
        nest.bindings.get("nest.db"), nest.bindings.get("nest.search"), registry=registry
    )
    print(f"✓ {done} entries indexed")
    return 0


def _types(args: argparse.Namespace) -> int:
    nest = _app(args.app)
    registry = nest.module_state["content"]["types"]
    for name, t in registry.types.items():
        fields = ", ".join(f"{n}:{f.type}" for n, f in t.fields.items()) or "no fields"
        print(f"{name:12} {t.path:28} {', '.join(t.taxonomies) or '-':20} {fields}")
    for name, tax in registry.taxonomies.items():
        print(f"{name:12} {tax.path:28} taxonomy{' (hierarchical)' if tax.hierarchical else ''}")
    return 0


def register(sub: Any) -> None:
    c = sub.add_parser("content", help="the CMS: imports and the search index")
    actions = c.add_subparsers(dest="content_command", required=True)

    p = actions.add_parser("import-wordpress", help="move a WordPress site in from its mysqldump")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--uploads", help="the site's wp-content/uploads folder")
    p.add_argument("--prefix", default="wp_")
    p.set_defaults(func=_wordpress)

    p = actions.add_parser(
        "import-geticus", help="move a Geticus site's pages, categories and menu in"
    )
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument(
        "--root", help="the site's folder (where assets/ is), to copy the images pages use"
    )
    p.add_argument("--plain-type", default="page", help="the type for entries in no category")
    p.add_argument(
        "--categorized-type", default="article", help="the type for entries in a category"
    )
    p.add_argument("--language", default="romanian", help="the menu language to take")
    p.set_defaults(func=_geticus)

    p = actions.add_parser("import-joomla", help="move a Joomla 1.5 site in from its mysqldump")
    p.add_argument("app")
    p.add_argument("dump")
    p.add_argument("--root", help="the site's folder (where images/ is)")
    p.add_argument("--prefix", default="jos_")
    p.add_argument("--type", default="page", help="the type the articles become")
    p.add_argument("--skip", default="404", help="aliases of articles to leave out, by commas")
    p.add_argument("--places", default="", help="the type GMapFP's places become")
    p.add_argument("--place-taxonomy", default="", help="the taxonomy of their categories")
    p.add_argument("--skip-place-categories", default="", help="GMapFP category ids to leave out")
    p.add_argument("--events", default="", help="the type the efemerides become")
    p.set_defaults(func=_joomla)

    p = actions.add_parser("reindex", help="rebuild the search index from the entries")
    p.add_argument("app")
    p.set_defaults(func=_reindex)

    p = actions.add_parser("types", help="the content types and taxonomies this application has")
    p.add_argument("app")
    p.set_defaults(func=_types)
