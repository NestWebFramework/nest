"""Where a map's pictures (tiles) come from: the providers the settings page offers.

Each preset is an address template, its credit, its closest zoom, whether it needs a
key, and its usual style. ``tiles(settings)`` turns the module's settings into what
the browser is given (the address with the key in, the credit, the zoom, the origin
the page policy must allow), or the problems that keep it from working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from markupsafe import escape

OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'


@dataclass(frozen=True)
class Preset:
    url: str
    attribution: str
    max_zoom: int
    needs_key: bool = False
    style: str = ""


PRESETS: dict[str, Preset] = {
    "osm": Preset("https://tile.openstreetmap.org/{z}/{x}/{y}.png", OSM, 19),
    "opentopomap": Preset(
        "https://tile.opentopomap.org/{z}/{x}/{y}.png",
        f'{OSM}, SRTM &middot; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
        17,
    ),
    "maptiler": Preset(
        "https://api.maptiler.com/maps/{style}/256/{z}/{x}/{y}.png?key={key}",
        f'<a href="https://www.maptiler.com/copyright/">&copy; MapTiler</a> {OSM}',
        20,
        needs_key=True,
        style="outdoor-v2",
    ),
    "thunderforest": Preset(
        "https://tile.thunderforest.com/{style}/{z}/{x}/{y}.png?apikey={key}",
        f'Maps &copy; <a href="https://www.thunderforest.com">Thunderforest</a>, data {OSM}',
        20,
        needs_key=True,
        style="outdoors",
    ),
    "stadia": Preset(
        "https://tiles.stadiamaps.com/tiles/{style}/{z}/{x}/{y}.png?api_key={key}",
        '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; '
        f'<a href="https://openmaptiles.org/">OpenMapTiles</a> {OSM}',
        20,
        needs_key=True,
        style="outdoors",
    ),
}

_KEY = re.compile(r"^[A-Za-z0-9._~-]{4,200}$")
_STYLE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass(frozen=True)
class Tiles:
    url: str  # the template Leaflet is given, the key in it
    attribution: str
    max_zoom: int
    origin: str  # what the page policy must let pictures come from


def _value(settings: Any, name: str) -> Any:
    return settings.get(name) if hasattr(settings, "get") else settings[name]


def problems(values: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """What keeps these settings from making a map: (message, params), to translate."""
    try:
        tiles(values)
    except TilesError as e:
        return [(e.message, e.params)]
    return []


class TilesError(ValueError):
    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.message = message
        self.params = params


def tiles(settings: Any) -> Tiles:
    provider = str(_value(settings, "provider") or "osm")
    key = str(_value(settings, "api_key") or "").strip()
    style = str(_value(settings, "style") or "").strip()
    credit = str(_value(settings, "attribution") or "").strip()
    zoom = int(_value(settings, "max_zoom") or 0)
    if key and not _KEY.match(key):
        raise TilesError("The API key holds characters a key does not have.")
    if style and not _STYLE.match(style):
        raise TilesError("A map style is a name of letters, digits, - and _.")
    if not 0 <= zoom <= 22:
        raise TilesError("The closest zoom is between 1 and 22 (0 takes the provider's).")
    if provider == "custom":
        url = str(_value(settings, "tiles") or "").strip()
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.netloc
            or not all(p in url for p in ("{z}", "{x}", "{y}"))
        ):
            raise TilesError("A custom tile address is https, with {z}, {x} and {y} in it.")
        if "{key}" in url and not key:
            raise TilesError("This tile address takes a key: fill in the API key.")
        template, default_credit, default_zoom = url, OSM, 19
    elif provider in PRESETS:
        p = PRESETS[provider]
        if p.needs_key and not key:
            raise TilesError("{provider} needs this site's API key.", provider=provider)
        template = p.url.replace("{style}", quote(style or p.style, safe=""))
        default_credit, default_zoom = p.attribution, p.max_zoom
    else:
        raise TilesError("Unknown map provider '{provider}'.", provider=provider)
    template = template.replace("{key}", quote(key, safe=""))
    parts = urlsplit(template)
    return Tiles(
        url=template,
        attribution=str(escape(credit)) if credit else default_credit,  # a typed credit is text
        max_zoom=zoom or default_zoom,
        origin=f"https://{parts.netloc}",
    )
