"""An in-process ``nest.cache``: an LRU dict with expiry."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class MemoryCache:
    def __init__(self, max_items: int = 10000):
        self._max = max(1, max_items)
        self._data: OrderedDict[str, tuple[str, float | None]] = OrderedDict()
        self._lock = asyncio.Lock()

    def _live(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.monotonic():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def _put(self, key: str, value: str, ttl: int | None) -> None:
        expires = time.monotonic() + ttl if ttl else None
        self._data[key] = (value, expires)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._put(key, value, ttl)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            value = int(self._live(key) or 0) + amount
            self._put(key, str(value), None)
            return value


def create(settings: Any, context: Any) -> MemoryCache:
    return MemoryCache(max_items=settings.max_items)
