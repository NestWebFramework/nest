"""Maps of places, on OpenStreetMap.

Maps and their markers are kept in the database and edited in the admin panel;
a page shows one with [map slug="..."] (WordPress's [wpgmza id="1"] still works
for a moved site). The module's page shows the main map with every place the
application's modules offer: a module that has places answers "map.points" with
a list of Points (or dicts with lat, lng, title, url, kind, description).
"""

from __future__ import annotations

from nest import ModuleHost
from nest_maps.service import MarkerData, Point
from nest_maps.web import admin, router, shortcode_map, shortcode_wpgmza

__all__ = ["MarkerData", "Point"]


def setup(host: ModuleHost) -> None:
    host.state.update(
        base="" if host.route in (None, "/") else host.route, settings=host.settings, host=host
    )

    from nest_maps.providers import problems

    host.check_settings(problems)  # the settings page refuses what cannot make a map
    from sqlalchemy.exc import SQLAlchemyError

    from nest_maps import service as maps_service

    db = host.bound("nest.db")
    maps_service.set_default(db, host.default_language)
    try:  # what was written before the text tables: its default language's rows, once
        maps_service.backfill(db, host.default_language)
    except SQLAlchemyError as e:
        host.log.warning(
            "maps: the text tables are not ready (%s); migrate the database", e.__class__.__name__
        )

    def seo_pages(_key: object = None) -> list[dict]:
        from nest_maps import service

        base, root = host.state["base"], host.admin_root
        out = [
            {
                "path": f"{base}/",
                "title": "Map",
                "kind": "map",
                "group": "Maps",
                "subject": "maps.index",
            }
        ]
        for m, _count in service.maps(host.bound("nest.db")):
            out.append(
                {
                    "path": f"{base}/{m.slug}/",
                    "title": m.title,
                    "subject": f"maps.map:{m.id}",
                    "description": m.description,
                    "kind": "map",
                    "group": "Maps",
                    "text": [m.description],
                    "edit": f"{root}/maps/{m.id}" if root else None,
                }
            )
        for locale in host.languages:  # each translated map at its address there
            if locale == host.default_language:
                continue
            for m, _count in service.maps(db):
                shown = service.shown_map(db, m, locale)
                if getattr(shown, "fallback", True):
                    continue
                out.append(
                    {
                        "path": host.language_url(f"{base}/{m.slug}/", locale),
                        "title": shown.title,
                        "subject": f"maps.map:{m.id}",
                        "description": shown.description,
                        "kind": "map",
                        "group": f"Maps · {locale.upper()}",
                        "language": locale,
                        "text": [shown.description],
                        "edit": f"{root}/translations/maps.map/{m.id}?lang={locale}"
                        if root
                        else None,
                    }
                )
        return out

    host.answer("seo.urls", seo_pages)

    def map_element(o: object) -> object:
        """A map another module puts on its page, from its own GeoJSON (markers, lines):
        {"request", "data": url, "lat", "lng", "zoom", "title", "fit"}."""
        from nest_maps.web import View, element

        if not isinstance(o, dict) or "request" not in o or not o.get("data"):
            return None
        view = View(
            float(o.get("lat") or 45.9),
            float(o.get("lng") or 24.9),
            int(o.get("zoom") or 7),
            str(o["data"]),
            str(o.get("title") or ""),
            fit=bool(o.get("fit", True)),
            refresh=int(o.get("refresh") or 0),
        )
        return element(o["request"], view)

    host.answer("maps.element", map_element)

    def near(q: object) -> dict | None:
        """The places on the maps near a point (the geo module's near-me page)."""
        from sqlalchemy import select

        from nest_maps.models import Map, Marker

        if not isinstance(q, dict):
            return None
        lat, lon, km = float(q["lat"]), float(q["lon"]), float(q.get("km") or 50)
        dlat, dlon = km / 111.0, km / 60.0  # a generous first cut; the distance decides
        db = host.bound("nest.db")
        with db.session() as s:
            rows = s.execute(
                select(Marker, Map)
                .join(Map, Map.id == Marker.map_id)
                .where(
                    Marker.lat.between(lat - dlat, lat + dlat),
                    Marker.lng.between(lon - dlon, lon + dlon),
                )
            ).all()
        import math

        def dist(m: object) -> float:
            p1, p2 = math.radians(lat), math.radians(m.lat)
            a = (
                math.sin((p2 - p1) / 2) ** 2
                + math.cos(p1) * math.cos(p2) * math.sin(math.radians(m.lng - lon) / 2) ** 2
            )
            return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))

        base = host.state.get("base", "")
        ranked = sorted(((m, mp, dist(m)) for m, mp in rows if m.title), key=lambda x: x[2])
        places = [
            {
                "title": m.title,
                "url": m.link or f"{base}/{mp.slug}",
                "km": round(d, 1),
                "note": mp.title,
            }
            for m, mp, d in ranked
            if d <= km
        ][: int(q.get("limit") or 10)]
        return (
            {"title": host.translator().gettext("Places on the maps"), "places": places}
            if places
            else None
        )

    host.answer("geo.near", near)
    host.shortcode("map", shortcode_map)
    host.shortcode("wpgmza", shortcode_wpgmza)
    host.admin(admin)
    host.mount(router)
