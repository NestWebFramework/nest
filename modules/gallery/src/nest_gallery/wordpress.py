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
        list(dump.rows(t("bwg_album_gallery"))) if t("bwg_album_gallery") in dump.columns else []
    )
    images = sorted(
        dump.rows(t("bwg_image")), key=lambda r: (int(r["gallery_id"]), int(r["order"] or 0))
    )

    wanted_albums: set[int] = set(albums) if everything else set()
    wanted_galleries: set[int] = set(galleries) if everything else set()
    for sid in used:
        sc = shortcodes.get(sid, {})
        if str(sc.get("album_id", "0")).isdigit() and int(sc.get("album_id", 0) or 0):
            wanted_albums.add(int(sc["album_id"]))
        if str(sc.get("gallery_id", "0")).isdigit() and int(sc.get("gallery_id", 0) or 0):
            wanted_galleries.add(int(sc["gallery_id"]))
    for link in links:  # an album brings what it holds
        if int(link["album_id"]) in wanted_albums and not int(link["is_album"]):
            wanted_galleries.add(int(link["alb_gal_id"]))
    report.skipped += len(set(galleries) - wanted_galleries)

    made: dict[int, int] = {}
    for gid in sorted(wanted_galleries):
        g = galleries.get(gid)
        if g is None:
            continue
        cover = (g.get("preview_image") or g.get("random_preview_image") or "").lstrip("/")
        c = service.ensure(
            db,
            _text(g["name"]),
            slug=_text(g["slug"]),
            description=_text(g["description"]),
            position=int(g["order"] or 0),
            published=str(g["published"]) == "1",
            cover=f"uploads/photo-gallery/{cover}" if cover else "",
        )
        made[gid] = c.id
        service.alias(db, "bwg_gallery", gid, c.id)
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
        report.photos += service.set_photos(db, c.id, photos)
        report.galleries += 1
    for aid in sorted(wanted_albums):
        a = albums.get(aid)
        if a is None:
            continue
        album = service.ensure(
            db,
            _text(a["name"]),
            slug=_text(a["slug"]),
            description=_text(a["description"]),
            position=int(a["order"] or 0),
            published=str(a["published"]) == "1",
        )
        service.alias(db, "bwg_album", aid, album.id)
        for link in sorted(
            (x for x in links if int(x["album_id"]) == aid), key=lambda x: int(x["order"] or 0)
        ):
            child = made.get(int(link["alb_gal_id"])) if not int(link["is_album"]) else None
            if child is not None:
                g = galleries[int(link["alb_gal_id"])]
                service.ensure(
                    db,
                    _text(g["name"]),
                    slug=_text(g["slug"]),
                    description=_text(g["description"]),
                    parent_id=album.id,
                    position=int(link["order"] or 0),
                    published=str(g["published"]) == "1",
                )
        report.albums += 1
    for sid, sc in shortcodes.items():  # what [Best_Wordpress_Gallery id=N] shows
        target = None
        if int(sc.get("album_id", 0) or 0) in wanted_albums:
            target = service.by_alias(db, "bwg_album", int(sc["album_id"]))
        elif int(sc.get("gallery_id", 0) or 0) in made:
            target = service.by_alias(db, "bwg_gallery", int(sc["gallery_id"]))
        if target is not None:
            service.alias(db, "bwg_shortcode", sid, target.id)


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
