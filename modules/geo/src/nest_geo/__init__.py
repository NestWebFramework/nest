"""Where the reader is, and what is near.

Distances (``distance_km``), a box around a point for a database's quick first cut
(``box``), and ranking places by distance (``near``) for any module; a page (at the
module's route) with a "locate me" button that asks the browser, then shows what every
module answering "geo.near" has near: stations, places on the maps, villages...

A module takes part with::

    host.answer("geo.near", lambda q: {"title": "Stations", "places": [
        {"title": ..., "url": ..., "km": ..., "note": ...}, ...]})

where ``q`` is {"lat", "lon", "km", "limit"}.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from nest import ModuleHost

__all__ = ["box", "distance_km", "near"]

EARTH_KM = 6371.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The distance between two points as the crow flies, in km (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_KM * 2 * math.asin(min(1.0, math.sqrt(a)))


def box(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) around a point, ``km`` each way: a quick first cut a
    database can index (``lat BETWEEN south AND north AND lon BETWEEN west AND east``)
    before the exact distance."""
    dlat = km / 111.32
    dlon = km / max(1e-6, 111.32 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def near[T](
    items: Iterable[T],
    lat: float,
    lon: float,
    where: Callable[[T], tuple[float | None, float | None]],
    *,
    km: float | None = None,
    limit: int = 10,
) -> list[tuple[T, float]]:
    """``items`` closest to a point first, with their distance (km, one decimal); those
    without a place, or farther than ``km``, left out."""
    ranked = []
    for item in items:
        a, b = where(item)
        if a is None or b is None:
            continue
        d = distance_km(lat, lon, a, b)
        if km is None or d <= km:
            ranked.append((item, round(d, 1)))
    ranked.sort(key=lambda x: x[1])
    return ranked[:limit]


def valid(lat: Any, lon: Any) -> tuple[float, float] | None:
    try:
        a, b = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (a, b) if -90 <= a <= 90 and -180 <= b <= 180 else None


def setup(host: ModuleHost) -> None:
    from nest_geo.web import router

    host.state.update(
        url="" if host.route in (None, "/") else host.route.rstrip("/"),
        radius_km=host.live("radius_km", int),
        limit=host.live("limit", int),
        gather=host.gather,
    )

    @host.context
    def _geo(request: Any) -> dict[str, Any]:
        url = host.state["url"]
        return {"geo_page": f"{url}/" if host.route is not None else None}

    if host.route is not None:
        host.mount(router)
