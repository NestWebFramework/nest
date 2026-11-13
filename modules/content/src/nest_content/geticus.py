"""Moving a Geticus site's pages in: entries, categories, the menu, the home page.

Geticus kept a content type's fields as columns of entries_data (field_id_N)
and an entry's body in its rich-text field. Here:

* categories become terms of the "category" taxonomy, parents kept;
* entries of a Geticus type become entries of a Nest type: those in a
  category become ``categorized_type`` (gari.ro: "article", at
  /cfr/{category}/{slug}), the rest ``plain_type`` ("page", at /{path});
  the body is the type's first rich-text field, sanitized, its images copied
  from the site's folder into storage and pointed at /media/;
* types that were only display templates (no entry with a slug) are left;
* an entry without a slug is left, except the home page;
* the menu's items in the site's language become the "main" menu: pages and
  category lists by reference, components by the address they now have;
* site_homepage becomes the home page.

Running it again updates what it brought.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from nest_db.mysqldump import Dump

from nest.text import slugify
from nest_content import service
from nest_content.service import EntryData

RICH_TEXT = {1, 2, 7, 6}  # CKEditor, TinyMCE, HTML, Textarea
_ASSET = re.compile(r"""(src|href)=(["'])(?:https?://[^/"']+)?/?(assets/cms/uploads/[^"']+)\2""")

# Where a Geticus component's pages are on the Nest site (gari.ro's).
COMPONENTS = {
    ("mersultrenurilor", "gari"): "/cfr/gari",
    ("mersultrenurilor", "harta"): "/cfr/harta",
    ("mersultrenurilor", "webmasteri"): "/cfr/webmasteri",
    ("mersultrenurilor", "localizare"): "/cfr/localizare",
    ("mersultrenurilor", "itinerariu"): "/cfr/itinerariu",
    ("galleries", "gallery"): "/galerii-foto",
}


@dataclass
class Report:
    terms: int = 0
    entries: int = 0
    files: int = 0
    menu_items: int = 0
    skipped: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _component_name(parameters: str) -> str:
    """The component's page from a PHP-serialized parameters string: s:4:"name";s:5:"harta"."""
    m = re.search(r's:4:"name";s:\d+:"([^"]*)"', parameters or "")
    return m.group(1) if m else ""


def import_dump(
    db: Any,
    search: Any,
    storage: Any,
    registry: Any,
    dump_path: Path,
    *,
    root: Path | None = None,
    plain_type: str = "page",
    categorized_type: str = "article",
    language: str = "romanian",
    settings: Any = None,
) -> Report:
    report = Report()
    d = Dump.read(dump_path)
    options = {r["slug"]: r["value"] for r in d.rows("settings")}
    home_id = int(options.get("site_homepage") or 0)

    # Categories, parents first.
    made: dict[int, int] = {}
    cats = sorted(
        d.rows("categories"), key=lambda c: (int(c["parent_id"] or 0) != 0, int(c["sort"] or 0))
    )
    if "category" in registry.taxonomies:
        for c in cats:
            t = service.ensure_term(
                db,
                registry,
                "category",
                html.unescape(c["title"]),
                slug=c["url_title"] or slugify(c["title"]),
                parent_id=made.get(int(c["parent_id"] or 0)),
                legacy_id=int(c["id"]),
                description=""
                if c.get("description") in (None, "None", "Some text here")
                else c["description"],
            )
            made[int(c["id"])] = t.id
            report.terms += 1

    # Which field holds each Geticus type's body.
    rich: dict[int, str] = {}
    for f in sorted(d.rows("content_fields"), key=lambda f: int(f["sort"] or 0)):
        if int(f["content_field_type_id"]) in RICH_TEXT:
            rich.setdefault(int(f["content_type_id"]), f"field_id_{f['id']}")
    data = {int(r["entry_id"]): r for r in d.rows("entries_data")}
    categories: dict[int, list[int]] = {}
    for link in d.rows("categories_entries"):
        if int(link["entry_id"] or 0) and int(link["category_id"] or 0) in made:
            categories.setdefault(int(link["entry_id"]), []).append(made[int(link["category_id"])])

    existing = {}
    for kind in (plain_type, categorized_type):
        for e in service.entries_of_type(db, kind, per_page=100000)[0]:
            if e.legacy_id is not None:
                existing[e.legacy_id] = e.id
    entry_ids: dict[int, int] = {}
    for e in sorted(d.rows("entries"), key=lambda e: int(e["id"])):
        eid = int(e["id"])
        slug = e["slug"] if e.get("slug") not in (None, "None", "") else ""
        if not slug and eid != home_id:
            report.skipped.append(f"#{eid} {e['title']} (no address)")
            continue
        field_name = rich.get(int(e["content_type_id"]))
        if field_name is None:
            report.skipped.append(f"#{eid} {e['title']} (a display template)")
            continue
        body = str((data.get(eid) or {}).get(field_name) or "")
        body = _assets(body, storage, root, report)
        cats_of = categories.get(eid, [])
        kind = categorized_type if cats_of and categorized_type in registry.types else plain_type
        modified = e.get("modified_date") or e.get("created_date")
        saved = service.save_entry(
            db,
            search,
            registry,
            EntryData(
                type=kind,
                title=html.unescape(e["title"]),
                slug=slug or slugify(e["title"]),
                keep_slug=bool(slug),
                status="published" if e["status"] == "published" else "draft",
                body=body,
                terms={"category": cats_of} if kind == categorized_type else {},
                published_at=_date(e.get("created_date")) or _date(modified),
                legacy_id=eid,
            ),
            existing_id=existing.get(eid),
        )
        entry_ids[eid] = saved.id
        report.entries += 1

    # The menu, in the site's language.
    items = [
        i
        for i in d.rows("navigation_items")
        if str(i.get("language")) == language and str(i.get("hide")) != "1"
    ]
    if items:
        menu = service.ensure_menu(db, "main", "Meniu")
        service.clear_menu(db, menu.id)
        ours: dict[int, int] = {}
        for i in sorted(items, key=lambda i: (int(i["parent_id"] or 0) != 0, int(i["sort"] or 0))):
            kind, url, entry_id, term_id = i["type"], "", None, None
            if kind == "page":
                entry_id = entry_ids.get(int(i["entry_id"] or 0))
            elif kind == "category_list":
                term_id = made.get(int(i["category_id"] or 0))
            elif kind == "component":
                url = COMPONENTS.get((i["component"], _component_name(i.get("parameters", ""))), "")
            elif kind == "url":
                url = i.get("url") or ""
            if not (url or entry_id or term_id):
                report.skipped.append(f"menu: {i['title']} ({i['component'] or kind})")
                continue
            item = service.add_menu_item(
                db,
                menu.id,
                title=html.unescape(i["title"]),
                url=url,
                entry_id=entry_id,
                term_id=term_id,
                parent_id=ours.get(int(i["parent_id"] or 0)),
                position=int(i["sort"] or 0),
                new_window=i.get("target") == "_blank",
            )
            ours[int(i["id"])] = item.id
            report.menu_items += 1

    if settings is not None and home_id in entry_ids:
        settings.set("content.home", service.entry(db, entry_ids[home_id]).path)
    return report


def _date(value: Any) -> datetime | None:
    if value in (None, "", "None", 0, "0"):
        return None
    if str(value).isdigit():
        return datetime.fromtimestamp(int(value))
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _assets(body: str, storage: Any, root: Path | None, report: Report) -> str:
    """Copy the images a body uses into storage; point them at /media/."""

    def replace(m: re.Match[str]) -> str:
        rel = unquote(
            html.unescape(m.group(3)).split("?")[0]
        )  # "Ramnicu%20Sarat/..." is a folder with a space
        if root is not None and storage.stat(rel) is None:
            source = root / rel
            if source.is_file():
                with source.open("rb") as f:
                    storage.put(rel, f)
                report.files += 1
            else:
                report.missing.append(rel)
        return f"{m.group(1)}={m.group(2)}/media/{quote(rel)}{m.group(2)}"

    return _ASSET.sub(replace, body)
