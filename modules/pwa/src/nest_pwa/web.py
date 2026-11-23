"""The web app's addresses, at the site's root whatever the module's route: the manifest,
the service worker (its scope is the folder it is served from, so it must be /sw.js), the
offline page, and the Android app links."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from nest import render, translator
from nest.host import module_state
from nest_pwa import core

root = APIRouter()


def _host(request: Request):
    return module_state(request, "pwa")["host"]


@root.get("/manifest.webmanifest", include_in_schema=False)
def manifest(request: Request) -> Response:
    nest = request.app.state.nest
    body = core.manifest(nest, _host(request).settings, translator(request))
    return Response(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        media_type="application/manifest+json",
        headers={"cache-control": "public, max-age=300"},
    )


@root.get("/sw.js", include_in_schema=False)
def service_worker(request: Request) -> Response:
    nest = request.app.state.nest
    return Response(
        core.worker(nest, _host(request).settings),
        media_type="text/javascript",
        # asked again on every visit: a new version must reach the browsers at once
        headers={"cache-control": "no-cache", "service-worker-allowed": "/"},
    )


@root.get("/offline", include_in_schema=False)
def offline(request: Request) -> Response:
    """Kept by the service worker when it starts; shown when a page is asked offline and
    no copy of it was kept. Lists the pages kept (its script reads them from the cache)."""
    response = render(request, "pwa/offline.html", pages_cache=core.PAGES_CACHE)
    response.headers["cache-control"] = "no-cache"
    return response


@root.get("/.well-known/assetlinks.json", include_in_schema=False)
def asset_links(request: Request) -> Response:
    links = core.asset_links(_host(request).settings)
    if links is None:
        raise HTTPException(status_code=404)
    return JSONResponse(links, headers={"cache-control": "public, max-age=3600"})
