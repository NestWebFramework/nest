"""Maps and markers: reading, saving, and the shapes the browser is given.

Markers are written as text, one a line, so an editor can paste them from
anywhere (OpenStreetMap shows a place's coordinates when it is clicked)::

    46.8575, 22.9179, Biserica de lemn, /obiective/biserica-de-lemn/
    46.8601, 22.9150, Fântâna din deal
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import delete, func, select

from nest_maps.models import Map, Marker


class MapsError(ValueError):
    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.message = message
        self.params = params


@dataclass
class MarkerData:
    lat: float
    lng: float
    title: str = ""
    link: str = ""
    description: str = ""


@dataclass
class Point:
    """A place to show on a map, from any module (an entry with coordinates, a marker)."""

    lat: float
    lng: float
    title: str
    url: str = ""
    kind: str = ""
    description: str = ""

    def feature(self) -> dict[str, Any]:
        props = {k: v for k, v in asdict(self).items() if k not in ("lat", "lng") and v}
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lng, self.lat]},
            "properties": props,
        }


@dataclass
class MapData:
    title: str
    lat: float
    lng: float
    zoom: int = 13
    slug: str = ""
    description: str = ""
    markers: list[MarkerData] = field(default_factory=list)
    legacy_id: int | None = None


def slugify(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:120] or "harta"


def coordinate(value: Any, *, lat: bool) -> float:
    """A latitude or a longitude, or MapsError."""
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise MapsError("'{value}' is not a coordinate.", value=value) from None
    limit = 90 if lat else 180
    if not -limit <= number <= limit:
        raise MapsError("'{value}' is not a coordinate.", value=value)
    return number


def safe_link(link: str) -> str:
    """A link a marker may carry: this site's path or an http(s) address."""
    link = (link or "").strip()
    if not link:
        return ""
    if (link.startswith("/") and not link.startswith("//")) or link.startswith(
        ("https://", "http://")
    ):
        return link[:500]
    raise MapsError(
        "A marker's link is a path on this site or an http(s) address: {link}", link=link
    )


def parse_markers(text: str) -> list[MarkerData]:
    """Markers from lines of "lat, lng, title, link"; a bad line is a MapsError naming it."""
    out = []
    for number, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",", 3)]
        if len(parts) < 2:
            raise MapsError("Line {n}: latitude, longitude, title, link.", n=number)
        try:
            lat, lng = coordinate(parts[0], lat=True), coordinate(parts[1], lat=False)
            link = safe_link(parts[3]) if len(parts) > 3 else ""
        except MapsError as e:
            raise MapsError("Line {n}: " + e.message, n=number, **e.params) from None
        out.append(MarkerData(lat, lng, parts[2][:200] if len(parts) > 2 else "", link))
    return out


def markers_text(markers: list[Marker]) -> str:
    return "\n".join(
        ", ".join(x for x in (f"{m.lat:.6f}", f"{m.lng:.6f}", m.title, m.link) if x != "")
        if m.title or m.link
        else f"{m.lat:.6f}, {m.lng:.6f}"
        for m in markers
    )


# --- reading -----------------------------------------------------------------------


def maps(db: Any) -> list[tuple[Map, int]]:
    with db.session() as s:
        counts = dict(s.execute(select(Marker.map_id, func.count()).group_by(Marker.map_id)).all())
        return [(m, counts.get(m.id, 0)) for m in s.scalars(select(Map).order_by(Map.title))]


def map_by(
    db: Any, *, slug: str | None = None, legacy_id: int | None = None, map_id: int | None = None
) -> Map | None:
    with db.session() as s:
        if map_id is not None:
            return s.get(Map, map_id)
        if legacy_id is not None:
            return s.scalar(select(Map).where(Map.legacy_id == legacy_id).limit(1))
        if slug:
            return s.scalar(select(Map).where(Map.slug == slug))
        return s.scalar(select(Map).order_by(Map.id).limit(1))


def markers(db: Any, map_id: int) -> list[Marker]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Marker).where(Marker.map_id == map_id).order_by(Marker.position, Marker.id)
            )
        )


def points(db: Any, map_id: int) -> list[Point]:
    return [
        Point(m.lat, m.lng, m.title, m.link, "marker", m.description) for m in markers(db, map_id)
    ]


def geojson(points: list[Point]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [p.feature() for p in points]}


# --- writing -----------------------------------------------------------------------


def save_map(db: Any, data: MapData, existing_id: int | None = None) -> Map:
    title = data.title.strip()
    if not title:
        raise MapsError("A map needs a title.")
    lat, lng = coordinate(data.lat, lat=True), coordinate(data.lng, lat=False)
    zoom = max(1, min(int(data.zoom or 13), 19))
    slug = slugify(data.slug or title)
    with db.session() as s, s.begin():
        clash = s.scalar(select(Map).where(Map.slug == slug, Map.id != (existing_id or 0)))
        if clash is not None:
            raise MapsError("Another map has the address '{slug}'.", slug=slug)
        if existing_id is None:
            m = Map(slug=slug, title=title, lat=lat, lng=lng, zoom=zoom)
            s.add(m)
        else:
            m = s.get(Map, existing_id)
            if m is None:
                raise MapsError("That map no longer exists.")
        m.slug, m.title, m.lat, m.lng, m.zoom = slug, title[:200], lat, lng, zoom
        m.description = data.description.strip()
        if data.legacy_id is not None:
            m.legacy_id = data.legacy_id
        s.flush()
        s.execute(delete(Marker).where(Marker.map_id == m.id))
        for i, mk in enumerate(data.markers):
            s.add(
                Marker(
                    map_id=m.id,
                    lat=mk.lat,
                    lng=mk.lng,
                    title=mk.title[:200],
                    link=mk.link,
                    description=mk.description,
                    position=i,
                )
            )
        s.flush()
        return m


def delete_map(db: Any, map_id: int) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Marker).where(Marker.map_id == map_id))
        s.execute(delete(Map).where(Map.id == map_id))
