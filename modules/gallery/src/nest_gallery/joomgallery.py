"""Galleries from a Joomla site's JoomGallery: its categories and their pictures.

JoomGallery kept its categories in a tree (parent) with a folder each (catpath) under
images/joomgallery/originals/ (and thumbnails/, details/); a picture is a file there
with a title and a text. The categories become galleries (their tree kept, their ids
kept as aliases of source "joomgallery"), the pictures their photos, the original
file and JoomGallery's thumbnail copied under joomgallery/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest_db import Dump

from nest.text import html_to_text
from nest_gallery import service, texts


@dataclass
class Report:
    galleries: int = 0
    photos: int = 0
    missing: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    text = "" if value in (None, "None") else str(value)
    return html_to_text(text).strip() if "<" in text or "&" in text else text.strip()


def _put(storage: Any, source: Path, key: str) -> bool:
    if not source.is_file():
        return False
    if storage.stat(key) is None:
        with source.open("rb") as f:
            storage.put(key, f)
    return True


def import_dump(
    db: Any, storage: Any, dump_path: Path, *, root: Path, prefix: str = "jos_"
) -> Report:
    """``root``: the site's folder, where images/joomgallery/ is."""
    report = Report()
    d = Dump.read(dump_path)
    base = root / "images" / "joomgallery"
    cats = {int(c["cid"]): c for c in d.rows(f"{prefix}joomgallery_catg") if c["published"] == 1}
    made: dict[int, int] = {}

    def depth(cid: int) -> int:
        n, parent = 0, int(cats[cid]["parent"] or 0)
        while parent in cats and n < 20:
            n, parent = n + 1, int(cats[parent]["parent"] or 0)
        return n

    for cid in sorted(cats, key=lambda c: (depth(c), int(cats[c]["ordering"] or 0))):
        c = cats[cid]
        made[cid] = service.ensure(
            db,
            _clean(c["name"]),
            slug=str(c.get("alias") or c["name"]),
            description=_clean(c["description"]),
            parent_id=made.get(int(c["parent"] or 0)),
            position=int(c["ordering"] or 0),
        ).id
        service.alias(db, "joomgallery", cid, made[cid])
        report.galleries += 1
    by_cat: dict[int, list[dict[str, str]]] = {}
    rows = sorted(
        d.rows(f"{prefix}joomgallery"), key=lambda r: (int(r["catid"]), -int(r["ordering"] or 0))
    )
    for img in rows:
        cid = int(img["catid"])
        if cid not in made or img["published"] != 1 or str(img.get("hidden", 0)) == "1":
            continue
        path = cats[cid]["catpath"]
        key = f"joomgallery/{path}/{img['imgfilename']}"
        # some sites kept only the resized "details" copy
        if not _put(storage, base / "originals" / path / img["imgfilename"], key) and not _put(
            storage, base / "details" / path / img["imgfilename"], key
        ):
            report.missing.append(f"{path}/{img['imgfilename']}")
            continue
        thumb = f"joomgallery/thumbnails/{path}/{img['imgthumbname']}"
        if not _put(storage, base / "thumbnails" / path / img["imgthumbname"], thumb):
            thumb = ""
        title, text = _clean(img["imgtitle"]), _clean(img["imgtext"])
        by_cat.setdefault(cid, []).append(
            {
                "key": key,
                "thumb": thumb,
                "caption": texts.caption(title),
                "alt": texts.alt(", ".join(x for x in (title, text) if x)) or texts.alt(title),
            }
        )
    for cid, photos in by_cat.items():
        report.photos += service.set_photos(db, made[cid], photos)
    return report
