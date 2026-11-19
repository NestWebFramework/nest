"""Moving a WordPress site in, from its mysqldump and its uploads folder.

What comes across: categories and tags (with their parents and ids), posts and
pages (published, draft and private; their slugs kept, so the addresses stay
the same), each post's categories and featured image, the attachments with the
files they name (and every resized copy, which old pages link to), the menus,
and the front page. Bodies get WordPress's paragraphs (wpautop) once, links to
the old site become relative, upload addresses become /media/uploads/..., and
everything is sanitized. Comments and gallery plugins are not moved yet.

Running it again updates what it brought the first time (matched by the
WordPress ids it keeps), so a site can be moved, checked, and moved again.
"""

from __future__ import annotations

import html
import mimetypes
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from nest_db import Dump
from sqlalchemy import select

from nest_content import service
from nest_content.html import autop
from nest_content.models import Entry
from nest_content.service import EntryData

STATUS = {
    "publish": "published",
    "draft": "draft",
    "pending": "draft",
    "private": "private",
    "future": "draft",
}


@dataclass
class Report:
    terms: int = 0
    entries: int = 0
    media: int = 0
    files: int = 0
    menus: int = 0
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _date(value: Any) -> datetime | None:
    if not value or str(value).startswith("0000"):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def rewrite(body: str, site_urls: list[str]) -> str:
    """Upload addresses to /media/uploads/, links to the old site to relative ones."""
    # Any upload address, on any host the site ever lived on (an old IP, a dev
    # copy under /morlaca/), is a file in the uploads folder.
    body = _UPLOADS.sub("/media/uploads/", body)
    for site in site_urls:
        base = site.rstrip("/")
        for scheme_less in {
            base,
            base.replace("http://", "https://"),
            base.replace("https://", "http://"),
        }:
            body = re.sub(re.escape(scheme_less) + r'(?=[/"\'])', "", body)
    return body


_UPLOADS = re.compile(r"""(?:https?:)?(?://[^/"'\s<>]+)?(?:/[^"'\s<>]*?)?/wp-content/uploads/""")


def import_dump(
    db: Any,
    search: Any,
    storage: Any,
    registry: Any,
    dump_path: Path,
    *,
    uploads: Path | None = None,
    prefix: str = "wp_",
    settings: Any = None,
) -> Report:
    report = Report()
    dump = Dump.read(dump_path)
    t = lambda name: f"{prefix}{name}"  # noqa: E731
    options = {r["option_name"]: r["option_value"] for r in dump.rows(t("options"))}
    sites = [u for u in {options.get("siteurl", ""), options.get("home", "")} if u]
    posts = {p["ID"]: p for p in dump.rows(t("posts"))}
    meta: dict[int, dict[str, Any]] = defaultdict(dict)
    for row in dump.rows(t("postmeta")):
        meta[row["post_id"]][row["meta_key"]] = row["meta_value"]

    # 1. Categories and tags, parents first.
    names = {r["term_id"]: r for r in dump.rows(t("terms"))}
    taxa = list(dump.rows(t("term_taxonomy")))
    by_taxonomy_id = {r["term_taxonomy_id"]: r for r in taxa}
    made: dict[int, int] = {}  # WordPress term_id -> our term id
    pending = [r for r in taxa if r["taxonomy"] in registry.taxonomies]
    for r in taxa:
        if r["taxonomy"] not in registry.taxonomies and r["taxonomy"] != "nav_menu":
            report.skipped.append(f"taxonomy {r['taxonomy']}")
    while pending:
        progress = False
        for r in list(pending):
            parent = r["parent"] or None
            if parent and parent not in made and any(p["term_id"] == parent for p in pending):
                continue
            term = names[r["term_id"]]
            created = service.ensure_term(
                db,
                registry,
                r["taxonomy"],
                html.unescape(term["name"]),
                slug=unquote(term["slug"]),
                parent_id=made.get(parent) if parent else None,
                description=r.get("description") or "",
                legacy_id=r["term_id"],
            )
            made[r["term_id"]] = created.id
            pending.remove(r)
            report.terms += 1
            progress = True
        if not progress:  # a parent that is not there: import the rest without it
            for r in pending:
                r["parent"] = 0
    relations: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for r in dump.rows(t("term_relationships")):
        tax = by_taxonomy_id.get(r["term_taxonomy_id"])
        if tax and tax["term_id"] in made:
            relations[r["object_id"]].append((tax["taxonomy"], made[tax["term_id"]]))

    # 2. Attachments and their files.
    media_keys: dict[int, str] = {}
    for p in posts.values():
        if p["post_type"] != "attachment":
            continue
        attached = meta[p["ID"]].get("_wp_attached_file")
        if not attached:
            continue
        key = f"uploads/{attached}"
        source = uploads / attached if uploads else None
        if source is None or not source.is_file():
            report.warnings.append(f"attachment {p['ID']}: {attached} is not in the uploads folder")
            continue
        with source.open("rb") as f:
            service.add_media(
                db,
                storage,
                key,
                f,
                filename=source.name,
                alt=meta[p["ID"]].get("_wp_attachment_image_alt") or "",
                title=html.unescape(p["post_title"] or ""),
                content_type=p.get("post_mime_type") or "",
                legacy_id=p["ID"],
            )
        media_keys[p["ID"]] = key
        report.media += 1
        stem = source.stem
        for variant in source.parent.glob(f"{stem}-*x*{source.suffix}"):  # the resized copies
            if re.fullmatch(re.escape(stem) + r"-\d+x\d+" + re.escape(source.suffix), variant.name):
                with variant.open("rb") as f:
                    storage.put(
                        f"uploads/{Path(attached).parent.as_posix()}/{variant.name}".replace(
                            "/./", "/"
                        ),
                        f,
                    )
                report.files += 1

    # Files a body links to that no attachment names (inserted by URL, plugins).
    linked: set[str] = set()
    for p in posts.values():
        if p["post_type"] in ("post", "page"):
            for m in re.finditer(r"/wp-content/uploads/([^\s\"'<>?#)]+)", p["post_content"] or ""):
                linked.add(unquote(m.group(1)))
    if uploads:
        for rel in sorted(linked):
            source = uploads / rel
            key = f"uploads/{rel}"
            if source.is_file() and storage.stat(key) is None:
                with source.open("rb") as f:
                    storage.put(key, f, mimetypes.guess_type(source.name)[0] or "")
                report.files += 1

    # 3. Posts and pages; parents before children.
    wanted = [
        p for p in posts.values() if p["post_type"] in registry.types and p["post_status"] in STATUS
    ]
    for p in posts.values():
        if p["post_type"] not in registry.types and p["post_type"] not in (
            "attachment",
            "revision",
            "nav_menu_item",
            "customize_changeset",
            "oembed_cache",
        ):
            report.skipped.append(f"{p['post_type']} {p['ID']}")
    wanted.sort(key=lambda p: (p["post_parent"] != 0, p["ID"]))
    entry_ids: dict[int, int] = {}
    with db.session() as s:
        for legacy, our in s.execute(
            select(Entry.legacy_id, Entry.id).where(Entry.legacy_id.is_not(None))
        ):
            entry_ids[legacy] = our
    for p in wanted:
        terms: dict[str, list[int]] = defaultdict(list)
        spec = registry.types[p["post_type"]]
        for taxonomy, term_id in sorted(relations.get(p["ID"], []), key=lambda x: x[1]):
            if taxonomy in spec.taxonomies:
                terms[taxonomy].append(term_id)
        body = rewrite(autop(p["post_content"] or ""), sites)
        thumbnail = meta[p["ID"]].get("_thumbnail_id")
        data = EntryData(
            type=p["post_type"],
            title=html.unescape(p["post_title"] or "") or f"#{p['ID']}",
            slug=unquote(p["post_name"] or "") or str(p["ID"]),
            keep_slug=bool(p["post_name"]),
            status=STATUS[p["post_status"]],
            excerpt=html.unescape(p["post_excerpt"] or ""),
            body=body,
            terms=dict(terms),
            parent_id=entry_ids.get(p["post_parent"]) if p["post_parent"] else None,
            position=p.get("menu_order") or 0,
            featured=media_keys.get(int(thumbnail), "") if str(thumbnail or "").isdigit() else "",
            published_at=_date(p.get("post_date")),
            legacy_id=p["ID"],
        )
        e = service.save_entry(db, search, registry, data, existing_id=entry_ids.get(p["ID"]))
        entry_ids[p["ID"]] = e.id
        report.entries += 1

    # 4. Menus.
    for r in taxa:
        if r["taxonomy"] != "nav_menu":
            continue
        term = names[r["term_id"]]
        menu = service.ensure_menu(db, unquote(term["slug"]), html.unescape(term["name"]))
        service.clear_menu(db, menu.id)
        items = sorted(
            (posts[x] for x, rel in relations_raw(dump, t, r["term_taxonomy_id"]) if x in posts),
            key=lambda p: p.get("menu_order") or 0,
        )
        ours: dict[int, int] = {}
        for p in sorted(
            items,
            key=lambda p: (
                int(meta[p["ID"]].get("_menu_item_menu_item_parent") or 0) != 0,
                p.get("menu_order") or 0,
            ),
        ):
            m = meta[p["ID"]]
            kind, obj = m.get("_menu_item_type"), int(m.get("_menu_item_object_id") or 0)
            parent = int(m.get("_menu_item_menu_item_parent") or 0)
            item = service.add_menu_item(
                db,
                menu.id,
                title=html.unescape(p["post_title"] or ""),
                url=rewrite(m.get("_menu_item_url") or "", sites) if kind == "custom" else "",
                entry_id=entry_ids.get(obj) if kind == "post_type" else None,
                term_id=made.get(obj) if kind == "taxonomy" else None,
                parent_id=ours.get(parent),
                position=p.get("menu_order") or 0,
                new_window=m.get("_menu_item_target") == "_blank",
            )
            ours[p["ID"]] = item.id
        report.menus += 1

    # 5. The front page.
    if settings is not None:
        if (
            options.get("show_on_front") == "page"
            and str(options.get("page_on_front", "")).isdigit()
        ):
            front = entry_ids.get(int(options["page_on_front"]))
            if front:
                e = service.entry(db, front)
                settings.set("content.home", e.path)
        if options.get("posts_per_page", "").isdigit():
            settings.set("content.per_page", int(options["posts_per_page"]))
    structure = options.get("permalink_structure", "")
    post_path = registry.types["post"].path if "post" in registry.types else ""
    wp_path = (
        structure.replace("%postname%", "{slug}")
        .replace("%category%", "{category}")
        .replace("%year%", "{year}")
        .replace("%monthnum%", "{month}")
        .replace("%day%", "{day}")
        .replace("%post_id%", "{id}")
    )
    if structure and wp_path != post_path:
        report.warnings.append(
            f"WordPress addressed posts as {structure}; this site as {post_path}. "
            f'Set content_types.post.path to "{wp_path}" to keep the old addresses.'
        )
    return report


def relations_raw(dump: Dump, t: Any, term_taxonomy_id: int) -> list[tuple[int, int]]:
    return [
        (r["object_id"], r["term_taxonomy_id"])
        for r in dump.rows(t("term_relationships"))
        if r["term_taxonomy_id"] == term_taxonomy_id
    ]


def site_options(dump_path: Path, prefix: str = "wp_") -> dict[str, Any]:
    dump = Dump.read(dump_path)
    return {
        r["option_name"]: r["option_value"]
        for r in dump.rows(f"{prefix}options")
        if r["option_name"]
        in ("blogname", "blogdescription", "siteurl", "home", "WPLANG", "permalink_structure")
    }


def host_of(url: str) -> str:
    return urlsplit(url).netloc
