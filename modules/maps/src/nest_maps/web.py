"""The maps over HTTP: the module's page, a page per map, GeoJSON, shortcodes, the editor.

A map in a page is a <div class="map"> carrying its centre and where its markers
are (GeoJSON); maps.js loads Leaflet only on a page that has one. The markers
are drawn from data, never from markup, so a title can hold nothing that runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from markupsafe import Markup, escape
from nest_auth import CurrentUser, require_role
from nest_db import Database
from starlette.concurrency import run_in_threadpool

from nest import admin_url, bound, is_htmx, render, toast, translator
from nest.host import module_state
from nest.security import CspError
from nest_maps import service
from nest_maps.providers import Tiles, TilesError, tiles
from nest_maps.service import MapData, MapsError, Point

log = logging.getLogger("nest.maps")
router = APIRouter()
admin = APIRouter()
editor = require_role("editor")


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "maps")


def _locale(request: Any) -> str:
    state = getattr(request, "state", None)
    return str(getattr(state, "locale", "") or "") if state is not None else ""


def _prefix(request: Any) -> str:
    """The page's language prefix ("/en"; "" for the default language, or without them)."""
    state = getattr(request, "state", None)
    return str(getattr(state, "url_prefix", "") or "") if state is not None else ""


def places(request: Request) -> list[Point]:
    """Every place the application's modules offer ("map.points"), as Points, in the
    page's language (a module that knows it answers with its words and addresses there)."""
    out: list[Point] = []
    for answer in request.app.state.nest.gather("map.points", {"locale": _locale(request)}):
        for p in answer or []:
            point = p if isinstance(p, Point) else Point(**p)
            out.append(point)
    return out


@dataclass
class View:
    """What a map element needs: where it opens and where its markers are."""

    lat: float
    lng: float
    zoom: int
    data: str
    title: str
    fit: bool = False
    refresh: int = 0  # seconds between asking for the markers again (0: once)


def current_tiles(request: Request) -> Tiles:
    """The tiles this application's settings ask for, the page policy letting them in; if
    the settings cannot make a map (a key missing), OpenStreetMap's, and a warning logged."""
    state = _state(request)
    try:
        found = tiles(state["settings"])
    except TilesError as e:
        log.warning("maps: %s; showing OpenStreetMap's tiles", e.message.format(**e.params))
        found = tiles(
            {"provider": "osm", "api_key": "", "style": "", "attribution": "", "max_zoom": 0}
        )
    try:
        state["host"].allow_source("img-src", found.origin, slot="tiles")
    except CspError:
        log.warning("maps: the page policy refuses %s", found.origin)
    return found


def element(request: Request, view: View) -> Markup:
    asset = request.app.state.nest.asset("maps", "maps.js")
    found = current_tiles(request)
    attrs = {
        "data-map": view.data,
        "data-lat": f"{view.lat:.6f}",
        "data-lng": f"{view.lng:.6f}",
        "data-zoom": str(view.zoom),
        "data-tiles": found.url,
        "data-attribution": found.attribution,
        "data-max-zoom": str(found.max_zoom),
        "aria-label": view.title,
        "role": "region",
    }
    if view.fit:
        attrs["data-fit"] = "1"
    if view.refresh:
        attrs["data-refresh"] = str(view.refresh)
    html = " ".join(f'{k}="{escape(v)}"' for k, v in attrs.items())
    osm = (
        f"https://www.openstreetmap.org/?mlat={view.lat:.5f}&amp;mlon={view.lng:.5f}"
        f"#map={view.zoom}/{view.lat:.5f}/{view.lng:.5f}"
    )
    t = translator(request)
    return Markup(
        f'<figure class="map-figure"><div class="map" {html}>'
        f'<a class="map-fallback" href="{osm}" rel="noopener">{escape(t("See it on OpenStreetMap"))}</a>'
        f'</div></figure><script src="{escape(asset)}" defer></script>'
    )


def _base(request: Request) -> str:
    return _state(request)["base"]


def map_view(request: Request, m: Any, *, with_places: bool = False) -> View:
    # asked under the page's language prefix, so its markers come in that language
    data = f"{_prefix(request)}{_base(request)}/{m.slug}.geojson" + (
        "?places=1" if with_places else ""
    )
    return View(m.lat, m.lng, m.zoom, data, m.title, fit=with_places)


# --- shortcodes --------------------------------------------------------------------


def shortcode_map(attrs: dict[str, str], ctx: Any) -> str:
    """[map slug="sat"], [map] (the main map), or [map lat=46.85 lng=22.91 zoom=14 title=".."];
    places="1" adds every place the site's modules know (as the module's own page)."""
    request = getattr(ctx, "request", ctx)
    if request is None:
        return ""
    db = request.app.state.nest.bindings.get("nest.db")
    if attrs.get("lat") and attrs.get("lng"):
        try:
            lat = service.coordinate(attrs["lat"], lat=True)
            lng = service.coordinate(attrs["lng"], lat=False)
            zoom = max(1, min(int(attrs.get("zoom", "14")), 19))
        except (MapsError, ValueError):
            return ""
        title = attrs.get("title", "")
        query = urlencode({"lat": lat, "lng": lng, "title": title[:200]})
        data = f"{_base(request)}/point.geojson?{query}"
        return element(request, View(lat, lng, zoom, data, title or "Map"))
    slug = attrs.get("slug") or _state(request)["settings"].get("main") or None
    m = service.map_by(db, slug=slug)
    with_places = attrs.get("places", "") in ("1", "true", "yes")
    return (
        element(
            request,
            map_view(request, service.shown_map(db, m, _locale(request)), with_places=with_places),
        )
        if m
        else ""
    )


def shortcode_wpgmza(attrs: dict[str, str], ctx: Any) -> str:
    """WordPress's [wpgmza id="1"]: the map imported from WP Google Maps with that id."""
    request = getattr(ctx, "request", ctx)
    if request is None or not attrs.get("id", "").isdigit():
        return ""
    db = request.app.state.nest.bindings.get("nest.db")
    m = service.map_by(db, legacy_id=int(attrs["id"]))
    return (
        element(request, map_view(request, service.shown_map(db, m, _locale(request)))) if m else ""
    )


# --- pages -------------------------------------------------------------------------


def _main(request: Request, db: Any) -> Any:
    return service.map_by(db, slug=_state(request)["settings"].get("main") or None)


@router.get("/")
def index(request: Request, db: Database = bound(Database)):
    m = _main(request, db)
    m = service.shown_map(db, m, _locale(request)) if m else None
    view = map_view(request, m, with_places=True) if m else None
    return render(
        request,
        "maps/map.html",
        map=m,
        figure=element(request, view) if view else None,
        places=sorted(places(request), key=lambda p: p.title.lower()),
        others=[
            service.shown_map(db, x, _locale(request))
            for x, _n in service.maps(db)
            if m is None or x.id != m.id
        ],
    )


@router.get("/point.geojson", include_in_schema=False)
def point(lat: float, lng: float, title: str = "") -> JSONResponse:
    try:
        p = Point(
            service.coordinate(lat, lat=True), service.coordinate(lng, lat=False), title[:200]
        )
    except MapsError:
        raise HTTPException(404) from None
    return _geo(service.geojson([p]))


def _geo(data: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        data, media_type="application/geo+json", headers={"Cache-Control": "public, max-age=300"}
    )


@router.get("/{slug}.geojson")
def map_geojson(request: Request, slug: str, db: Database = bound(Database)) -> JSONResponse:
    m = service.map_by(db, slug=slug)
    if m is None:
        raise HTTPException(404)
    prefix = _prefix(request)
    found = [  # a marker's link to a page of the site, at that page's address in this language
        replace(p, url=prefix + p.url)
        if prefix and p.url.startswith("/") and not p.url.startswith("//")
        else p
        for p in service.points(db, m.id, _locale(request))
    ]
    if request.query_params.get("places") == "1":
        found += places(request)
    return _geo(service.geojson(found))


@router.get("/{slug}/")
def map_page(request: Request, slug: str, db: Database = bound(Database)):
    m = service.map_by(db, slug=slug)
    if m is None:
        raise HTTPException(404)
    m = service.shown_map(db, m, _locale(request))
    if getattr(m, "fallback", False):  # not translated: the original's words, said so
        request.state.language_fallback = True
        request.state.alternates = {request.app.state.nest.catalogs.default: request.url.path}
    return render(
        request,
        "maps/map.html",
        map=m,
        figure=element(request, map_view(request, m)),
        places=[],
        others=[],
    )


@router.get("/{slug}")
def map_without_slash(slug: str, request: Request) -> RedirectResponse:
    return RedirectResponse(f"{_base(request)}/{slug}/", status_code=301)


# --- editing -----------------------------------------------------------------------


@admin.get("/")
def admin_list(
    request: Request, user: CurrentUser = Depends(editor), db: Database = bound(Database)
):
    maps = service.maps(db)
    main = _main(request, db)
    settings = _state(request)["settings"]
    return render(
        request,
        "maps/editor/list.html",
        maps=maps,
        base=_base(request),
        provider=settings.get("provider"),
        preview=element(request, map_view(request, main)) if main else None,
    )


def _values(m: Any = None, marks: list[Any] | None = None) -> dict[str, Any]:
    if m is None:
        return {
            "title": "",
            "slug": "",
            "description": "",
            "lat": "",
            "lng": "",
            "zoom": 13,
            "markers": "",
        }
    return {
        "title": m.title,
        "slug": m.slug,
        "description": m.description,
        "lat": f"{m.lat:.6f}",
        "lng": f"{m.lng:.6f}",
        "zoom": m.zoom,
        "markers": service.markers_text(marks or []),
    }


@admin.get("/new")
def admin_new(request: Request, user: CurrentUser = Depends(editor)):
    return render(request, "maps/editor/edit.html", values=_values(), map=None, error=None)


@admin.get("/{map_id:int}")
def admin_edit(
    request: Request,
    map_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    m = service.map_by(db, map_id=map_id)
    if m is None:
        raise HTTPException(404)
    return render(
        request,
        "maps/editor/edit.html",
        values=_values(m, service.markers(db, m.id)),
        map=m,
        error=None,
        base=_base(request),
    )


async def _save(request: Request, map_id: int | None) -> Response:
    db = request.app.state.nest.bindings.get("nest.db")
    form = await request.form()
    values = {
        k: str(form.get(k, ""))
        for k in ("title", "slug", "description", "lat", "lng", "zoom", "markers")
    }
    try:
        zoom = int(values["zoom"] or 13)
    except ValueError:
        zoom = 13
    try:
        data = MapData(
            title=values["title"],
            slug=values["slug"],
            description=values["description"],
            lat=service.coordinate(values["lat"], lat=True),
            lng=service.coordinate(values["lng"], lat=False),
            zoom=zoom,
            markers=service.parse_markers(values["markers"]),
        )
        problem = request.app.state.nest.lookup("seo.check", {"form": form})
        if problem:
            raise MapsError(problem)
        m = await run_in_threadpool(service.save_map, db, data, map_id)
        request.app.state.nest.lookup("seo.save", {"subject": f"maps.map:{m.id}", "form": form})
    except MapsError as err:
        existing = service.map_by(db, map_id=map_id) if map_id else None
        return render(
            request,
            "maps/editor/edit.html",
            fragment="form" if is_htmx(request) else None,
            status_code=200 if is_htmx(request) else 400,
            values=values,
            map=existing,
            error=translator(request)(err.message, **err.params),
            base=_base(request),
            posted=form,
        )
    toast(request, translator(request)("Saved."))
    target = admin_url(request, "maps", f"{m.id}?saved=1")
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


@admin.post("/new")
async def admin_create(request: Request, user: CurrentUser = Depends(editor)):
    return await _save(request, None)


@admin.post("/{map_id:int}")
async def admin_update(request: Request, map_id: int, user: CurrentUser = Depends(editor)):
    return await _save(request, map_id)


@admin.post("/{map_id:int}/delete")
def admin_delete(
    request: Request,
    map_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    service.delete_map(db, map_id)
    toast(request, translator(request)("Deleted."))
    return RedirectResponse(admin_url(request, "maps"), status_code=303)
