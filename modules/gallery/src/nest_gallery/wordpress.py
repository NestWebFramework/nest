"""Galleries from WordPress plugins: Photo Gallery (10Web, "bwg") and NextGEN ("ngg").

A gallery's photos and thumbnails are copied from the site's folders into
nest.storage under the same relative paths. The plugins' shortcodes are not
rewritten in the pages: their ids are kept as aliases, and the gallery module
answers [Best_Wordpress_Gallery id=2] and [nggallery id=1] itself, so imported
pages stay exactly as they were written.

By default only the galleries a published page uses are moved (an album brings
its galleries); ``everything=True`` moves them all.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest_db.mysqldump import Dump

from nest.shortcodes import attributes
from nest_gallery import service


@dataclass
class Report:
    galleries: int = 0
    albums: int = 0
    photos: int = 0
    skipped: int = 0
    missing: list[str] = field(default_factory=list)


_TAG = re.compile(r"\[(Best_Wordpress_Gallery|nggallery|ngg)(\s[^\]]*)?\]", re.I)


def _copy(storage: Any, source: Path, key: str, report: Report) -> bool:
    if not source.is_file():
        report.missing.append(str(source))
        return False
    if storage.stat(key) is None:
        with source.open("rb") as f:
            storage.put(key, f)
    return True


def _text(value: Any) -> str:
    return html.unescape(str(value or "")).strip()


def import_dump(
    db: Any,
    storage: Any,
    dump_path: Path,
    *,
    uploads: Path,
    prefix: str = "wp_",
    everything: bool = False,
) -> Report:
    report = Report()
    dump = Dump.read(dump_path)
    t = lambda name: f"{prefix}{name}"  # noqa: E731
    used_bwg: set[int] = set()
    used_ngg: set[int] = set()
    for p in dump.rows(t("posts")):
        if p["post_status"] != "publish" or p["post_type"] in ("revision", "nav_menu_item"):
            continue
        for m in _TAG.finditer(p["post_content"] or ""):
            attrs = attributes(m.group(2) or "")
            value = (attrs.get("id") or attrs.get("ids") or "").split(",")[0].strip()
            if value.isdigit():
                (used_bwg if m.group(1).lower() == "best_wordpress_gallery" else used_ngg).add(
                    int(value)
                )
    if t("bwg_gallery") in dump.columns:
        _bwg(db, storage, dump, t, uploads / "photo-gallery", used_bwg, everything, report)
    if t("ngg_gallery") in dump.columns:
        _ngg(db, storage, dump, t, uploads.parent.parent, used_ngg, everything, report)
    return report


def _bwg(
    db, storage, dump, t, root: Path, used: set[int], everything: bool, report: Report
) -> None:
    shortcodes = {
        int(r["id"]): attributes(r["tagtext"] or "") for r in dump.rows(t("bwg_shortcode"))
    }
    galleries = {int(r["id"]): r for r in dump.rows(t("bwg_gallery"))}
    albums = (
        {int(r["id"]): r for r in dump.rows(t("bwg_album"))}
        if t("bwg_album") in dump.columns
        else {}
    )
    links = (
        sorted(dump.rows(t("bwg_album_gallery")), key=lambda x: int(x["order"] or 0))
        if t("bwg_album_gallery") in dump.columns
        else []
    )
    images = sorted(
        dump.rows(t("bwg_image")), key=lambda r: (int(r["gallery_id"]), int(r["order"] or 0))
    )

    def number(value: Any) -> int:
        return int(value) if str(value or "").isdigit() else 0

    # What pages use: the albums and galleries their shortcodes name...
    wanted_albums: set[int] = set(albums) if everything else set()
    wanted_galleries: set[int] = set(galleries) if everything else set()
    for sid in used:
        sc = shortcodes.get(sid, {})
        if number(sc.get("album_id")):
            wanted_albums.add(number(sc.get("album_id")))
        if number(sc.get("gallery_id")):
            wanted_galleries.add(number(sc.get("gallery_id")))
    # ...and everything those albums hold, albums inside albums included.
    frontier = list(wanted_albums)
    while frontier:
        aid = frontier.pop()
        for link in links:
            if int(link["album_id"]) != aid:
                continue
            child = int(link["alb_gal_id"])
            if int(link["is_album"]):
                if child not in wanted_albums:
                    wanted_albums.add(child)
                    frontier.append(child)
            else:
                wanted_galleries.add(child)
    report.skipped += len(set(galleries) - wanted_galleries)

    # A collection's parent and place: the first album that holds it.
    parent_of: dict[tuple[str, int], tuple[int, int]] = {}
    for link in links:
        key = ("bwg_album" if int(link["is_album"]) else "bwg_gallery", int(link["alb_gal_id"]))
        if int(link["album_id"]) in wanted_albums and key not in parent_of:
            parent_of[key] = (int(link["album_id"]), int(link["order"] or 0))

    made: dict[tuple[str, int], int] = {}

    def create(source: str, legacy_id: int, row: dict, cover: str = "") -> int:
        c = service.ensure(
            db,
            _text(row["name"]),
            slug=_text(row["slug"]),
            description=_text(row["description"]),
            position=int(row["order"] or 0),
            published=str(row["published"]) == "1",
            cover=cover,
        )
        service.alias(db, source, legacy_id, c.id)
        made[(source, legacy_id)] = c.id
        return c.id

    for aid in sorted(wanted_albums):
        if aid in albums:
            create("bwg_album", aid, albums[aid])
            report.albums += 1
    for gid in sorted(wanted_galleries):
        g = galleries.get(gid)
        if g is None:
            continue
        preview = (g.get("preview_image") or g.get("random_preview_image") or "").lstrip("/")
        cid = create("bwg_gallery", gid, g, f"uploads/photo-gallery/{preview}" if preview else "")
        photos = []
        for img in (
            i for i in images if int(i["gallery_id"]) == gid and str(i["published"]) == "1"
        ):
            rel, thumb = img["image_url"].lstrip("/"), (img["thumb_url"] or "").lstrip("/")
            key, thumb_key = (
                f"uploads/photo-gallery/{rel}",
                f"uploads/photo-gallery/{thumb}" if thumb else "",
            )
            if not _copy(storage, root / rel, key, report):
                continue
            if thumb and not _copy(storage, root / thumb, thumb_key, report):
                thumb_key = ""
            photos.append(
                {
                    "key": key,
                    "thumb": thumb_key,
                    "caption": _text(img["description"]),
                    "alt": _text(img["alt"]),
                }
            )
        report.photos += service.set_photos(db, cid, photos)
        report.galleries += 1

    for (
        source,
        legacy_id,
    ), cid in made.items():  # now that every album exists, hang each in its place
        parent = parent_of.get((source, legacy_id))
        row = albums[legacy_id] if source == "bwg_album" else galleries[legacy_id]
        parent_id = made.get(("bwg_album", parent[0])) if parent else None
        service.ensure(
            db,
            _text(row["name"]),
            slug=_text(row["slug"]),
            description=_text(row["description"]),
            parent_id=parent_id if parent_id != cid else None,
            position=parent[1] if parent else int(row["order"] or 0),
            published=str(row["published"]) == "1",
        )

    for sid, sc in shortcodes.items():  # what [Best_Wordpress_Gallery id=N] shows
        target = made.get(("bwg_album", number(sc.get("album_id")))) or made.get(
            ("bwg_gallery", number(sc.get("gallery_id")))
        )
        if target is not None:
            service.alias(db, "bwg_shortcode", sid, target)


def _ngg(
    db, storage, dump, t, wp_root: Path, used: set[int], everything: bool, report: Report
) -> None:
    pictures = sorted(
        dump.rows(t("ngg_pictures")),
        key=lambda r: (int(r["galleryid"]), int(r["sortorder"] or 0), int(r["pid"])),
    )
    for g in dump.rows(t("ngg_gallery")):
        gid = int(g["gid"])
        if not everything and gid not in used:
            report.skipped += 1
            continue
        folder = (g["path"] or "").strip("/")
        c = service.ensure(
            db,
            _text(g["title"]) or _text(g["name"]),
            slug=_text(g["name"]),
            description=_text(g["galdesc"]),
        )
        service.alias(db, "ngg_gallery", gid, c.id)
        photos = []
        for p in (x for x in pictures if int(x["galleryid"]) == gid and not int(x["exclude"] or 0)):
            name = p["filename"]
            key, thumb_key = f"{folder}/{name}", f"{folder}/thumbs/thumbs_{name}"
            if not _copy(storage, wp_root / folder / name, key, report):
                continue
            if not _copy(
                storage, wp_root / folder / "thumbs" / f"thumbs_{name}", thumb_key, report
            ):
                thumb_key = ""
            photos.append(
                {
                    "key": key,
                    "thumb": thumb_key,
                    "caption": _text(p["description"]),
                    "alt": _text(p["alttext"]),
                }
            )
        report.photos += service.set_photos(db, c.id, photos)
        report.galleries += 1
