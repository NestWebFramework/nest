"""The ``nest.storage`` interface."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable

__all__ = ["Storage", "Stat", "clean_key", "StorageError"]


class StorageError(ValueError):
    pass


_SEGMENT = re.compile(r"^[^\x00-\x1f/\\]{1,200}$")


def clean_key(key: str) -> str:
    """A key as a safe relative path, or StorageError: no '..', no '/' start, no control bytes."""
    key = key.strip().replace("\\", "/").strip("/")
    parts = key.split("/")
    if (
        not key
        or len(key) > 1000
        or any(p in ("", ".", "..") or not _SEGMENT.match(p) for p in parts)
    ):
        raise StorageError(f"not a storage key: {key!r}")
    return "/".join(parts)


@dataclass(frozen=True)
class Stat:
    key: str
    size: int
    modified: float
    content_type: str


@runtime_checkable
class Storage(Protocol):
    def put(self, key: str, data: bytes | BinaryIO, content_type: str = "") -> Stat:
        """Store a file under ``key``, replacing what was there."""
        ...

    def open(self, key: str) -> BinaryIO:
        """The file for reading. FileNotFoundError when there is none."""
        ...

    def stat(self, key: str) -> Stat | None: ...

    def delete(self, key: str) -> None: ...

    def keys(self, prefix: str = "") -> Iterator[str]: ...

    def local_path(self, key: str) -> str | None:
        """A path on this machine, when the provider has one (so a server can send it directly)."""
        ...
