"""The hello application's home page."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Request
from nest_cache import Cache

from nest import ModuleHost, bound, render

router = APIRouter()
host: ModuleHost  # set in setup()


@router.get("/")
async def index(request: Request, cache: Cache = bound(Cache)):
    count = int(await cache.get("hello:count") or 0)
    return render(request, "home/index.html", count=count, greeting=host.settings.get("greeting"))


@router.post("/count")
async def count(request: Request, cache: Cache = bound(Cache)):
    value = await cache.incr("hello:count")
    if request.headers.get("hx-request") == "true":
        return render(request, "home/index.html", fragment="counter", count=value, greeting="")
    return render(request, "home/index.html", count=value, greeting=host.settings.get("greeting"))


def clock_event() -> tuple[str, str]:
    now = datetime.now().strftime("%H:%M:%S")
    return "clock", host.render_block("home/index.html", "clock", now=now)


async def tick() -> None:
    """Publish the time each second, only while someone is watching. Every worker ticks
    for its own visitors, so the tick is not relayed to the others."""
    while True:
        await asyncio.sleep(1)
        if host.realtime.subscribers("clock"):
            host.realtime.publish("clock", *clock_event(), local=True)


def setup(module_host: ModuleHost) -> None:
    global host
    host = module_host
    host.realtime.topic("clock", public=True, snapshot=clock_event)
    host.background(tick)
    host.mount(router)
