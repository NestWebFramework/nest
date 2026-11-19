"""WP Google Maps (wpgmza) into the maps module: each map with its centre, zoom and
markers, keeping its id so [wpgmza id="1"] in a moved page still shows it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest_db.mysqldump import Dump

from nest_maps import service
from nest_maps.service import MapData, MapsError, MarkerData


@dataclass
class Report:
    maps: int = 0
    markers: int = 0
    skipped: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def import_dump(db: Any, dump_path: Path, *, prefix: str = "wp_") -> Report:
    report = Report()
    dump = Dump.read(dump_path)
    if f"{prefix}wpgmza_maps" not in dump.columns:
        report.skipped.append("no WP Google Maps tables in this dump")
        return report
    by_map: dict[int, list[MarkerData]] = {}
    if f"{prefix}wpgmza" in dump.columns:
        for r in dump.rows(f"{prefix}wpgmza"):
            if _text(r.get("approved")) == "0":
                continue
            try:
                lat = service.coordinate(r["lat"], lat=True)
                lng = service.coordinate(r["lng"], lat=False)
            except MapsError:
                report.skipped.append(f"marker {r.get('id')}: no coordinates")
                continue
            try:
                link = service.safe_link(_text(r.get("link")))
            except MapsError:
                link = ""
            by_map.setdefault(int(r["map_id"]), []).append(
                MarkerData(
                    lat,
                    lng,
                    _text(r.get("title")) or _text(r.get("address")),
                    link,
                    _text(r.get("description")),
                )
            )
    for r in dump.rows(f"{prefix}wpgmza_maps"):
        if _text(r.get("active")) == "1":  # WP Google Maps marks a deleted map active=1
            report.skipped.append(f"map {r['id']}: deleted in WordPress")
            continue
        legacy = int(r["id"])
        title = _text(r.get("map_title")) or f"Harta {legacy}"
        try:
            lat = service.coordinate(r["map_start_lat"], lat=True)
            lng = service.coordinate(r["map_start_lng"], lat=False)
        except MapsError:
            report.skipped.append(f"map {legacy}: no centre")
            continue
        existing = service.map_by(db, legacy_id=legacy)
        marks = by_map.get(legacy, [])
        service.save_map(
            db,
            MapData(
                title=title,
                lat=lat,
                lng=lng,
                zoom=int(_text(r.get("map_start_zoom")) or 13),
                slug=existing.slug if existing else "",
                markers=marks,
                legacy_id=legacy,
            ),
            existing.id if existing else None,
        )
        report.maps += 1
        report.markers += len(marks)
    return report
