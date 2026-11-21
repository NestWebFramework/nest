"""``nest translations``: where every language stands, and translating elsewhere.

nest translations status APP
nest translations export APP FILE.json --lang en [--subject content.entry] [--only todo]
nest translations import APP FILE.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _app(app: str) -> tuple[Any, dict[str, Any], list[str], str]:
    from nest.host import create_app

    nest = create_app(app, environ={**os.environ}).state.nest
    state = nest.module_state.get("translations")
    if state is None:
        raise SystemExit(f"{app} does not include the translations module")
    return nest, state, list(nest.site_languages), nest.catalogs.default


def _status(args: argparse.Namespace) -> int:
    from nest_translations import service

    _nest, state, site, default = _app(args.app)
    targets = [x for x in site if x != default]
    if not state["kinds"]:
        print("none of the application's modules translates its records")
        return 0
    print(f"{'':28}" + "".join(f"{x:>36}" for x in targets))
    for kind in state["kinds"].values():
        stand = service.states(state["db"], kind, site, default)
        cells = []
        for x in targets:
            c = service.counts(stand, x)
            cells.append(
                f"{c['published']:>6} ok {c['outdated']:>4} old {c['draft']:>4} draft {c['missing']:>5} none"
            )
        print(f"{kind.subject:28}" + "".join(f"{c:>36}" for c in cells))
    return 0


def _export(args: argparse.Namespace) -> int:
    from nest_translations import service
    from nest_translations.kinds import TranslationsError

    _nest, state, site, default = _app(args.app)
    kinds = state["kinds"]
    if args.subject and args.subject not in kinds:
        print(
            f"✗ {args.subject} is not translated here ({', '.join(kinds) or 'nothing is'})",
            file=sys.stderr,
        )
        return 1
    chosen = [kinds[args.subject]] if args.subject else list(kinds.values())
    try:
        data = service.export(state["db"], chosen, args.lang, site, default, args.only)
    except TranslationsError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    Path(args.file).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(data['items'])} texts to {args.file}")
    return 0


def _import(args: argparse.Namespace) -> int:
    from nest_translations import service
    from nest_translations.kinds import TranslationsError

    _nest, state, site, default = _app(args.app)
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        written, refused, touched = service.import_(
            state["db"], state["kinds"], data, site, default
        )
        for subject, ids in touched.items():
            state["announce"](subject, ids, [data["locale"]])
    except (OSError, json.JSONDecodeError, TranslationsError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"✓ {written} translations saved")
    for line in refused:
        print(f"  ✗ {line}", file=sys.stderr)
    return 1 if refused else 0


def register(sub: Any) -> None:
    g = sub.add_parser("translations", help="every module's records in every language")
    actions = g.add_subparsers(dest="translations_command", required=True)

    p = actions.add_parser("status", help="where every language stands, per kind of record")
    p.add_argument("app")
    p.set_defaults(func=_status)

    p = actions.add_parser(
        "export", help="a language's texts beside their originals, to translate elsewhere"
    )
    p.add_argument("app")
    p.add_argument("file")
    p.add_argument("--lang", required=True, help="the language to translate into")
    p.add_argument("--subject", help="one kind of record (content.entry); all by default")
    p.add_argument(
        "--only",
        default="todo",
        choices=["todo", "missing", "outdated", "draft", "published", "all"],
        help="todo: missing, outdated and drafts",
    )
    p.set_defaults(func=_export)

    p = actions.add_parser("import", help="bring translations back from an export")
    p.add_argument("app")
    p.add_argument("file")
    p.set_defaults(func=_import)
