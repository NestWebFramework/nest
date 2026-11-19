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
        return out

    host.answer("seo.urls", seo_pages)
    host.shortcode("map", shortcode_map)
    host.shortcode("wpgmza", shortcode_wpgmza)
    host.admin(admin)
    host.mount(router)
