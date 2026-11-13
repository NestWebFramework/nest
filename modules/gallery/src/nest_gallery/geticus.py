"""Galleries from a Geticus site (gari.ro): the galleries tree and gallery_images.

Geticus kept galleries in a tree (parent_id) and each photo as a path under
the site's folder, with a thumbnail under assets/cms/uploads/.thumbs/. Slugs
keep Geticus's aliases, so /galerii-foto/<alias> answers where it did; ids are
kept as aliases, so [geticus_gallery id=N] (a station's photos, say) works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest_db.mysqldump import Dump

from nest.text import html_to_text
from nest_gallery import service


@dataclass
class Report:
    galleries: int = 0
    photos: int = 0
    missing: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    text = "" if value in (None, "None") else str(value)
    return html_to_text(text) if "<" in text or "&" in text else text.strip()


def import_dump(db: Any, storage: Any, dump_path: Path, *, root: Path) -> Report:
    report = Report()
    d = Dump.read(dump_path)
    galleries = {
        int(g["id"]): g for g in d.rows("galleries") if str(g.get("status")) == "published"
    }
    made: dict[int, int] = {}
    for gid, g in sorted(galleries.items(), key=lambda x: int(x[1]["sort"] or 0)):
        c = service.ensure(
            db,
            _clean(g["title"]),
            slug=str(g["alias"] or g["title"]),
            description=_clean(g["description"]),
            position=int(g["sort"] or 0),
        )
        made[gid] = c.id
        service.alias(db, "geticus_gallery", gid, c.id)
        report.galleries += 1
    for gid, g in galleries.items():  # the tree, once every gallery exists
        parent = made.get(int(g["parent_id"] or 0))
        if parent and parent != made[gid]:
            service.ensure(
                db,
                _clean(g["title"]),
                slug=str(g["alias"] or g["title"]),
                description=_clean(g["description"]),
                parent_id=parent,
                position=int(g["sort"] or 0),
            )
    images = sorted(
        d.rows("gallery_images"), key=lambda r: (int(r["gallery_id"]), int(r["sort"] or 0))
    )
    by_gallery: dict[int, list[dict]] = {}
    for img in images:
        gid = int(img["gallery_id"])
        if gid not in made or str(img.get("hide", "0")) == "1":
            continue
        rel = str(img["filename"]).lstrip("/")
        source = root / rel
        if not source.is_file():
            report.missing.append(rel)
            continue
        if storage.stat(rel) is None:
            with source.open("rb") as f:
                storage.put(rel, f)
        thumb_rel = rel.replace("assets/cms/uploads/", "assets/cms/uploads/.thumbs/", 1)
        thumb = ""
        if thumb_rel != rel and (root / thumb_rel).is_file():
            if storage.stat(thumb_rel) is None:
                with (root / thumb_rel).open("rb") as f:
                    storage.put(thumb_rel, f)
            thumb = thumb_rel
        by_gallery.setdefault(gid, []).append(
            {
                "key": rel,
                "thumb": thumb,
                "caption": _clean(img["title"]),
                "alt": _clean(img["alt"]) or _clean(img["title"]),
            }
        )
    for gid, photos in by_gallery.items():
        report.photos += service.set_photos(db, made[gid], photos)
    return report
