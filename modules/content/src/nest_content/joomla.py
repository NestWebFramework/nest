"""Moving a Joomla 1.5 site in, from its mysqldump and its folder.

What comes across: the published articles (by type, their aliases as slugs), the
pictures they show from images/ (copied to /media/uploads/), the places of the
GMapFP map as entries of a type with coordinates (address, phones, web, hours; the
map's categories as terms), and the "on this day" events of the efemerides
component as entries with their date. Plugin tags ({gmapfp}, {mosimage}...) go;
{zoomin src="big"}small{/zoomin} becomes a picture linking to the big one. Contact
persons named in a place's text are left out: they were people, not the place.

Ids are kept, so running it again updates what it brought: articles keep Joomla's
id; places and events, which had their own numbering, are kept apart from them by
PLACE and EVENT added to theirs.
"""

from __future__ import annotations

import html
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from nest_db import Dump
from sqlalchemy import select

from nest_content import service
from nest_content.html import strip_joomla_tags
from nest_content.models import Entry
from nest_content.service import EntryData

PLACE = 1_000_000  # a GMapFP place's id + PLACE is its entry's legacy id
EVENT = 2_000_000  # an efemeride's id + EVENT


@dataclass
class Report:
    entries: int = 0
    places: int = 0
    events: int = 0
    terms: int = 0
    files: int = 0
    skipped: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _date(value: Any) -> datetime | None:
    if not value or str(value).startswith("0000"):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


_ZOOMIN = re.compile(r'\{zoomin\s+src="([^"]+)"\s*\}(.*?)\{/zoomin\}', re.I | re.S)
_ANY_TAG = re.compile(r"\{/?[a-z][a-z0-9_]*(?:\s[^{}]*)?\}", re.I)
_IMAGES = re.compile(
    r"""(?<=["'(])(?:https?://[^/"']+)?/?images/((?:stories|joomgallery)/[^"')\s]+)"""
)
_EMPTY = re.compile(r"<(p|td|span|strong)[^>]*>(?:\s|&nbsp;|\xa0|<br\s*/?>)*</\1>\s*", re.I)
# a place's lines naming a person: who to ask for, the agency's head
_PERSON = re.compile(
    r"<p[^>]*>\s*<(?:b|strong)>\s*(?:Persoana de contact|Sef agentie|Şef agenţie)[^<]*</(?:b|strong)>.*?</p>\s*",
    re.I | re.S,
)


def body_of(markup: str) -> tuple[str, list[str]]:
    """An article's text for Nest, and the files under images/ it shows."""
    text = _ZOOMIN.sub(
        lambda m: f'<a href="{m.group(1)}"><img src="{m.group(2).strip()}" alt=""></a>',
        markup or "",
    )
    text = strip_joomla_tags(text)
    text = _ANY_TAG.sub("", text)  # any other plugin's tag points at nothing here
    files = sorted({m.group(1) for m in _IMAGES.finditer(text)})
    text = _IMAGES.sub(lambda m: f"/media/uploads/{m.group(1)}", text)
    for _ in range(3):  # the cells and paragraphs the tags leave empty, nested
        text = _EMPTY.sub("", text)
    return text.strip(), files


def place_text(row: dict[str, Any]) -> str:
    return _PERSON.sub("", row.get("intro") or "").strip()


def _hours(markup: str) -> str:
    """'<p><b>Orar: </b>L-V: 08:00-20:00</p>' -> 'L-V: 08:00-20:00'."""
    text = re.sub(r"<(?:b|strong)>\s*(?:Orar|Program)[^<]*</(?:b|strong)>\s*:?", "", markup or "")
    text = re.sub(r"<br\s*/?>|</p>\s*<p[^>]*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [re.sub(r"[ \t\xa0]+", " ", x).strip(" :") for x in text.splitlines()]
    return "\n".join(x for x in lines if x)


def _web(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.startswith(("http://", "https://")) else f"http://{value}"


def _copy(storage: Any, root: Path | None, rel: str, report: Report) -> None:
    key = f"uploads/{rel}"
    if root is None or storage.stat(key) is not None:
        return
    source = root / "images" / rel
    if not source.is_file():
        report.missing.append(f"images/{rel}")
        return
    with source.open("rb") as f:
        storage.put(key, f, mimetypes.guess_type(source.name)[0] or "")
    report.files += 1


def import_dump(
    db: Any,
    search: Any,
    storage: Any,
    registry: Any,
    dump_path: Path,
    *,
    root: Path | None = None,
    prefix: str = "jos_",
    article_type: str = "page",
    skip: set[str] = frozenset({"404"}),
    place_type: str = "",
    place_taxonomy: str = "",
    skip_place_categories: set[int] = frozenset(),
    event_type: str = "",
) -> Report:
    """Bring the site in. ``skip``: aliases of articles left out. ``place_type``,
    ``event_type``: the types the map's places and the efemerides become (left out
    when empty or not a type of the site)."""
    report = Report()
    d = Dump.read(dump_path)
    table = lambda name: f"{prefix}{name}"  # noqa: E731
    known: dict[int, int] = {}
    with db.session() as s:
        for legacy, our in s.execute(
            select(Entry.legacy_id, Entry.id).where(Entry.legacy_id.is_not(None))
        ):
            known[legacy] = our

    def save(data: EntryData) -> None:
        e = service.save_entry(db, search, registry, data, existing_id=known.get(data.legacy_id))
        known[data.legacy_id] = e.id

    # 1. Articles.
    if article_type not in registry.types:
        raise ValueError(f"'{article_type}' is not a content type of this site")
    for a in d.rows(table("content")):
        if a["state"] != 1 or a["alias"] in skip:
            report.skipped.append(f"article {a['alias']}")
            continue
        body, files = body_of((a["introtext"] or "") + (a["fulltext"] or ""))
        for rel in files:
            _copy(storage, root, rel, report)
        save(
            EntryData(
                type=article_type,
                title=html.unescape(a["title"]),
                slug=a["alias"] or str(a["id"]),
                keep_slug=bool(a["alias"]),
                status="published",
                body=body,
                published_at=_date(a.get("publish_up")) or _date(a.get("created")),
                legacy_id=a["id"],
            )
        )
        report.entries += 1

    # 2. The map's places.
    if place_type and place_type in registry.types and table("gmapfp") in d.tables():
        spec = registry.types[place_type]
        categories = {
            c["id"]: c for c in d.rows(table("categories")) if c["section"] == "com_gmapfp"
        }
        terms: dict[int, int] = {}
        if place_taxonomy and place_taxonomy in spec.taxonomies:
            for cid, c in categories.items():
                if cid in skip_place_categories:
                    continue
                made = service.ensure_term(
                    db,
                    registry,
                    place_taxonomy,
                    html.unescape(c["title"]),
                    slug=c.get("alias") or "",
                    legacy_id=PLACE + cid,
                )
                terms[cid] = made.id
                report.terms += 1
        for p in d.rows(table("gmapfp")):
            if p["published"] != 1 or p["catid"] in skip_place_categories:
                report.skipped.append(f"place {p['alias']}")
                continue
            phones = ", ".join(x.strip() for x in (p["tel"], p["tel2"]) if x and x.strip())
            address = ", ".join(x.strip() for x in (p["adresse"], p["adresse2"]) if x and x.strip())
            values = {
                "address": address,
                "postal_code": (p.get("codepostal") or "").strip(),
                "phone": phones,
                "web": _web(p["web"]),
                "hours": _hours(p["horaires_prix"]),
                "lat": p["glat"],
                "lng": p["glng"],
            }
            save(
                EntryData(
                    type=place_type,
                    title=html.unescape(p["nom"]).strip(),
                    slug=p["alias"] or str(p["id"]),
                    keep_slug=bool(p["alias"]),
                    status="published",
                    body=place_text(p),
                    fields={k: v for k, v in values.items() if k in spec.fields and v},
                    terms={place_taxonomy: [terms[p["catid"]]]} if p["catid"] in terms else {},
                    legacy_id=PLACE + p["id"],
                )
            )
            report.places += 1

    # 3. On this day.
    if event_type and event_type in registry.types and table("efemerides") in d.tables():
        for ev in d.rows(table("efemerides")):
            if ev["published"] != 1:
                continue
            when = str(ev["historicdate"] or "")[:10]
            try:
                day = date.fromisoformat(when)
            except ValueError:
                report.skipped.append(f"event {ev['id']} (no date)")
                continue
            save(
                EntryData(
                    type=event_type,
                    title=html.unescape(ev["title"]).strip(),
                    slug=ev.get("alias") or "",
                    status="published",
                    body=body_of(ev.get("description") or "")[0],
                    fields={"date": day} if "date" in registry.types[event_type].fields else {},
                    legacy_id=EVENT + ev["id"],
                )
            )
            report.events += 1
    return report
