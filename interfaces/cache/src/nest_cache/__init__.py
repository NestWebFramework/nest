"""The ``nest.cache`` interface."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> str | None:
        """The value stored under ``key``, or None."""
        ...

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Store ``value``; it expires after ``ttl`` seconds when given."""
        ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, amount: int = 1) -> int:
        """Add ``amount`` to an integer value (0 when absent) and return it."""
        ...
