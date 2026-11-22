"""An in-process ``nest.cache``: an LRU dict with expiry, capped by entries and by size.

Each worker has its own; when either cap is passed, the least recently used entries go
first. For one cache shared by every worker, bind redis instead (capped by its own
``maxmemory``)."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class MemoryCache:
    def __init__(self, max_items: int = 10000, max_mb: float = 8.0):
        self._max = max(1, max_items)
        self._max_bytes = int(max(0.1, max_mb) * 1024 * 1024)
        self._bytes = 0
        self._data: OrderedDict[str, tuple[str, float | None]] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def _size(key: str, value: str) -> int:
        return len(key) + len(value) + 64  # the entry's own keeping, roughly

    @property
    def used_bytes(self) -> int:
        return self._bytes

    def _drop(self, key: str) -> None:
        item = self._data.pop(key, None)
        if item is not None:
            self._bytes -= self._size(key, item[0])

    def _live(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.monotonic():
            self._drop(key)
            return None
        self._data.move_to_end(key)
        return value

    def _put(self, key: str, value: str, ttl: int | None) -> None:
        if self._size(key, value) > self._max_bytes // 4:  # one entry never takes the cache
            return
        expires = time.monotonic() + ttl if ttl else None
        self._drop(key)
        self._data[key] = (value, expires)
        self._bytes += self._size(key, value)
        while len(self._data) > self._max or self._bytes > self._max_bytes:
            old, (v, _e) = self._data.popitem(last=False)
            self._bytes -= self._size(old, v)

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._put(key, value, ttl)

    async def delete(self, key: str) -> None:
        self._drop(key)

    async def incr(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        async with self._lock:
            current = self._live(key)
            if current is None:
                self._put(key, str(amount), ttl)
                return amount
            value = int(current) + amount
            expires = self._data[key][1]  # keeps its expiry
            self._drop(key)
            self._data[key] = (str(value), expires)
            self._bytes += self._size(key, str(value))
            return value


def create(settings: Any, context: Any) -> MemoryCache:
    return MemoryCache(max_items=settings.max_items, max_mb=getattr(settings, "max_mb", 8.0))
