"""``nest.storage`` in an S3-compatible object store, through MinIO's client.

Every key goes through ``clean_key`` and under the application's prefix, so one bucket
holds several applications and no key escapes its own. A file is streamed to and from
the store, never kept whole in memory beyond what the caller handed over.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any, BinaryIO

from nest_storage import Stat, StorageError, clean_key


def _secret(value: Any) -> str:
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value or "")


class S3Storage:
    def __init__(self, client: Any, bucket: str, prefix: str):
        self.client, self.bucket = client, bucket
        self.prefix = f"{prefix.strip('/')}/" if prefix else ""

    def _key(self, key: str) -> str:
        return self.prefix + clean_key(key)

    def put(self, key: str, data: bytes | BinaryIO, content_type: str = "") -> Stat:
        name = self._key(key)
        if isinstance(data, (bytes, bytearray)):
            stream, length = io.BytesIO(bytes(data)), len(data)
        else:
            stream, length = data, -1  # unknown length: the client sends it in parts
        self.client.put_object(
            self.bucket,
            name,
            stream,
            length,
            content_type=content_type or "application/octet-stream",
            part_size=10 * 1024 * 1024 if length < 0 else 0,
        )
        found = self.stat(key)
        if found is None:
            raise StorageError(f"{key} was not stored")
        return found

    def open(self, key: str) -> BinaryIO:
        try:
            response = self.client.get_object(self.bucket, self._key(key))
        except Exception as e:
            if _missing(e):
                raise FileNotFoundError(key) from None
            raise
        return _Body(response)  # type: ignore[return-value]

    def stat(self, key: str) -> Stat | None:
        try:
            o = self.client.stat_object(self.bucket, self._key(key))
        except Exception as e:
            if _missing(e):
                return None
            raise
        modified = o.last_modified.timestamp() if o.last_modified else 0.0
        return Stat(
            key=clean_key(key),
            size=int(o.size or 0),
            modified=modified,
            content_type=o.content_type or "",
        )

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, self._key(key))

    def keys(self, prefix: str = "") -> Iterator[str]:
        start = self.prefix + (clean_key(prefix) if prefix else "")
        for o in self.client.list_objects(self.bucket, prefix=start, recursive=True):
            yield o.object_name[len(self.prefix) :]

    def local_path(self, key: str) -> str | None:
        return None  # served by streaming: the files are on another machine


class _Body:
    """The store's answer as a file to read; its connection given back when closed."""

    def __init__(self, response: Any):
        self.response = response

    def read(self, size: int = -1) -> bytes:
        return self.response.read(None if size is None or size < 0 else size)

    def __iter__(self) -> Iterator[bytes]:
        return iter(lambda: self.read(64 * 1024), b"")

    def close(self) -> None:
        self.response.close()
        self.response.release_conn()

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _missing(error: Exception) -> bool:
    return getattr(error, "code", "") in ("NoSuchKey", "NoSuchObject", "NoSuchBucket")


def create(settings: Any, context: Any, client: Any = None) -> S3Storage:
    if client is None:
        from minio import Minio  # noqa: PLC0415

        client = Minio(
            settings.endpoint,
            access_key=_secret(settings.access_key),
            secret_key=_secret(settings.secret_key),
            secure=bool(settings.secure),
            region=settings.region or None,
        )
    if settings.create_bucket and not client.bucket_exists(settings.bucket):
        client.make_bucket(settings.bucket)
    return S3Storage(client, settings.bucket, settings.prefix or context.app)
