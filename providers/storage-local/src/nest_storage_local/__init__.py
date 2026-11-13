"""A workspace folder as ``nest.storage``."""

from __future__ import annotations

import mimetypes
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from nest_storage import Stat, StorageError, clean_key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / clean_key(key)).resolve()
        if not path.is_relative_to(self.root):  # a symlink pointing out, for one
            raise StorageError(f"not a storage key: {key!r}")
        return path

    def put(self, key: str, data: bytes | BinaryIO, content_type: str = "") -> Stat:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as out:
                if isinstance(data, bytes | bytearray):
                    out.write(data)
                else:
                    shutil.copyfileobj(data, out, 1024 * 1024)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return self.stat(key)  # type: ignore[return-value]

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def stat(self, key: str) -> Stat | None:
        path = self._path(key)
        if not path.is_file():
            return None
        st = path.stat()
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return Stat(key=clean_key(key), size=st.st_size, modified=st.st_mtime, content_type=kind)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def keys(self, prefix: str = "") -> Iterator[str]:
        base = self._path(prefix) if prefix else self.root
        if base.is_file():
            yield clean_key(prefix)
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.startswith(".upload-"):
                yield path.relative_to(self.root).as_posix()

    def local_path(self, key: str) -> str | None:
        return str(self._path(key))


def create(settings: Any, context: Any) -> LocalStorage:
    return LocalStorage(context.path(settings.root))
