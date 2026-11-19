"""``nest.cache`` and ``nest.pubsub`` on Redis or Valkey, shared by every worker and machine.

Each worker makes its own client after the fork (nest serve does not preload the
application), so no connection crosses processes. Values are strings, as the
interface says; a counter's expiry is set only when it is made, in the same round
trip as the increment, so a window cannot be stretched by hitting it.

A subscription holds a connection of its own while it listens; the realtime broker
keeps one per worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis


class RedisProvider:
    """Both interfaces on one client (and its pool of connections)."""

    def __init__(self, client: Any, prefix: str):
        self._r = client
        self._p = f"{prefix}:" if prefix else ""

    async def get(self, key: str) -> str | None:
        value = await self._r.get(self._p + key)
        return value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self._r.set(self._p + key, value, ex=ttl or None)

    async def delete(self, key: str) -> None:
        await self._r.delete(self._p + key)

    async def incr(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        name = self._p + key
        if not ttl:
            return int(await self._r.incrby(name, amount))
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.set(name, 0, ex=ttl, nx=True)  # made now, with its expiry; else untouched
            pipe.incrby(name, amount)
            _made, value = await pipe.execute()
        return int(value)

    async def publish(self, channel: str, message: str) -> None:
        await self._r.publish(self._p + channel, message)

    async def messages(self, channel: str) -> AsyncIterator[str]:
        pubsub = self._r.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(self._p + channel)
        try:
            while True:
                # waits up to a second at a time, so the socket timeout never fires on quiet
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None and message.get("type") == "message":
                    data = message["data"]
                    yield data.decode() if isinstance(data, bytes) else str(data)
        finally:
            await pubsub.aclose()

    async def ping(self) -> bool:
        return bool(await self._r.ping())

    async def aclose(self) -> None:
        await self._r.aclose()

    def close(self) -> None:
        """Before the fork (nest serve's preflight): nothing was opened outside a loop."""


def create(settings: Any, context: Any) -> RedisProvider:
    url = settings.url
    url = url.get_secret_value() if hasattr(url, "get_secret_value") else str(url)
    client = Redis.from_url(
        url,
        socket_timeout=settings.timeout,
        socket_connect_timeout=settings.timeout,
        max_connections=settings.max_connections,
        health_check_interval=30,
    )
    return RedisProvider(client, settings.prefix or context.app)
