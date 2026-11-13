"""Runtime settings: values a person may change on a running application.

Build and deploy facts stay in ``module.yml``; secrets stay in the environment;
this store holds the rest, as RoboHub's settings module does: namespaced keys
(``glossary.per_page``) in ``data/settings.conf``. Only declared keys exist,
each typed by its spec. A value set in the environment wins and is read-only.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nest.bind import env_name
from nest.manifest import SettingSpec

_MISSING = object()


class SettingsError(Exception):
    pass


def _coerce(spec: SettingSpec, value: Any, key: str) -> Any:
    if value is None:
        return None
    try:
        if spec.type == "bool":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off"):
                return False
            raise ValueError(value)
        if spec.type == "int":
            return int(value)
        if spec.type == "float":
            return float(value)
        return str(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{key}: '{value}' is not a {spec.type}") from None


class SettingsStore:
    def __init__(self, path: Path, app: str, environ: Mapping[str, str]):
        self._path = path
        self._app = app
        self._environ = environ
        self._specs: dict[str, tuple[str, str, SettingSpec]] = {}
        self._lock = threading.Lock()
        self._values = self._read()

    def declare(self, owner: str, specs: Mapping[str, SettingSpec]) -> None:
        for key, spec in specs.items():
            self._specs[f"{owner}.{key}"] = (owner, key, spec)

    def _read(self) -> dict[str, str]:
        values = {}
        if self._path.is_file():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
        return values

    def _spec(self, key: str) -> tuple[str, str, SettingSpec]:
        if key not in self._specs:
            raise SettingsError(f"'{key}' is not a declared setting")
        return self._specs[key]

    def get(self, key: str, default: Any = _MISSING) -> Any:
        owner, name, spec = self._spec(key)
        var = env_name(self._app, owner, name)
        if var in self._environ:
            return _coerce(spec, self._environ[var], key)
        if key in self._values:
            return _coerce(spec, self._values[key], key)
        if default is not _MISSING:
            return default
        return _coerce(spec, spec.default, key)

    def set(self, key: str, value: Any) -> None:
        owner, name, spec = self._spec(key)
        if spec.secret:
            raise SettingsError(f"{key} is secret; it is set in the environment only")
        if env_name(self._app, owner, name) in self._environ:
            raise SettingsError(f"{key} is set by the environment and cannot be changed here")
        text = "" if value is None else str(_coerce(spec, value, key))
        if "\n" in text:
            raise SettingsError(f"{key}: a value is one line")
        with self._lock:
            self._values[key] = text
            tmp = self._path.with_suffix(".tmp")
            body = "".join(f"{k}={v}\n" for k, v in sorted(self._values.items()))
            tmp.write_text(body, encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)

    def items(self) -> list[tuple[str, Any]]:
        return [(key, self.get(key)) for key in sorted(self._specs)]


class Namespaced:
    """One module's view of the store: ``get("per_page")`` is ``glossary.per_page``."""

    def __init__(self, store: SettingsStore, owner: str):
        self._store = store
        self._owner = owner

    def get(self, key: str, default: Any = _MISSING) -> Any:
        return self._store.get(f"{self._owner}.{key}", default)

    def set(self, key: str, value: Any) -> None:
        self._store.set(f"{self._owner}.{key}", value)
