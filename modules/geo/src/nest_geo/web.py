"""The near-me page: a button that asks the browser where it is, and what every module
has near that point."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from nest import render
from nest.host import module_state
from nest.security import allow
from nest_geo import valid

router = APIRouter()


def _state(request: Request) -> dict[str, Any]:
    return module_state(request, "geo")


def groups(request: Request, lat: float, lon: float) -> list[dict[str, Any]]:
    state = _state(request)
    q = {"lat": lat, "lon": lon, "km": state["radius_km"], "limit": state["limit"]}
    out = []
    for answer in state["gather"]("geo.near", q):
        if isinstance(answer, dict) and answer.get("places"):
            out.append(answer)
    return out


@router.get("/")
def page(request: Request, lat: str = "", lon: str = ""):
    point = valid(lat, lon) if lat or lon else None
    response = render(
        request,
        "geo/near.html",
        fragment="near" if point and request.headers.get("hx-request") else None,
        point=point,
        groups=groups(request, *point) if point else [],
        action=f"{_state(request)['url']}/",
    )
    return allow(response, "geolocation")


@router.get("/places")
def places(request: Request, lat: str, lon: str):
    point = valid(lat, lon)
    if point is None:
        raise HTTPException(400)
    return render(
        request,
        "geo/near.html",
        fragment="near",
        point=point,
        groups=groups(request, *point),
        action=f"{_state(request)['url']}/",
    )
