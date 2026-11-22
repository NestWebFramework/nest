"""Runtime settings: values a person may change on a running application.

Build and deploy facts stay in ``module.yml``; secrets stay in the environment;
this store holds the rest. A value is found in the environment, then in this
store, then in what the application's manifest sets for the module
(``modules: [{name: glossary, config: {per_page: 50}}]``), then in the module's
default. The store holds values as RoboHub's settings module does: namespaced keys
(``glossary.per_page``) in ``data/settings.conf``. Only declared keys exist,
each typed by its spec. A value set in the environment wins and is read-only.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nest.bind import env_name
from nest.manifest import SettingSpec

_MISSING = object()
CHECK_EVERY = 2.0  # seconds between looks at the settings file


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
    def __init__(self, path: Path, app: str, environ: Mapping[str, str], secret: str = ""):
        self._path = path
        self._app = app
        self._environ = environ
        # secrets set in the admin panel are kept encrypted (AES-GCM, under a key derived from
        # the application's secret key, which stays in the environment): never in clear on disk
        self._box = hashlib.sha256(f"nest-settings:{secret}".encode()).digest() if secret else b""
        self._specs: dict[str, tuple[str, str, SettingSpec]] = {}
        self._instance: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._values = self._read()
        self._seen = self._stamp()
        self._checked = time.monotonic()

    def declare(
        self,
        owner: str,
        specs: Mapping[str, SettingSpec],
        instance: Mapping[str, Any] | None = None,
    ) -> None:
        """A module's settings; ``instance`` is what the application's manifest sets for it."""
        for key, spec in specs.items():
            self._specs[f"{owner}.{key}"] = (owner, key, spec)
        for key, value in (instance or {}).items():
            if key in specs:
                self._instance[f"{owner}.{key}"] = _coerce(specs[key], value, f"{owner}.{key}")

    def _read(self) -> dict[str, str]:
        values = {}
        if self._path.is_file():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
        return values

    def _stamp(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def _fresh(self) -> None:
        """Another process (a second worker, the command line) may have changed the file:
        it is read again when it did, looked at no more than every CHECK_EVERY seconds."""
        now = time.monotonic()
        if now - self._checked < CHECK_EVERY:
            return
        self._checked = now
        stamp = self._stamp()
        if stamp != self._seen:
            with self._lock:
                self._values = self._read()
                self._seen = stamp

    def _spec(self, key: str) -> tuple[str, str, SettingSpec]:
        if key not in self._specs:
            raise SettingsError(f"'{key}' is not a declared setting")
        return self._specs[key]

    def declared(self, key: str) -> bool:
        """Whether ``key`` ("owner.name") is a setting some package declared."""
        return key in self._specs

    def get(self, key: str, default: Any = _MISSING) -> Any:
        owner, name, spec = self._spec(key)
        self._fresh()
        var = env_name(self._app, owner, name)
        if var in self._environ:
            return _coerce(spec, self._environ[var], key)
        if key in self._values:
            if spec.secret:
                return self._open(key, self._values[key])
            return _coerce(spec, self._values[key], key)
        if key in self._instance:
            return self._instance[key]
        if default is not _MISSING:
            return default
        return _coerce(spec, spec.default, key)

    def set(self, key: str, value: Any) -> None:
        owner, name, spec = self._spec(key)
        if spec.secret:
            self._set_secret(key, owner, name, value)
            return
        if env_name(self._app, owner, name) in self._environ:
            raise SettingsError(f"{key} is set by the environment and cannot be changed here")
        text = "" if value is None else str(_coerce(spec, value, key))
        if "\n" in text:
            raise SettingsError(f"{key}: a value is one line")
        number = _coerce(spec, value, key) if spec.type in ("int", "float") else None
        if number is not None and spec.min is not None and number < spec.min:
            raise SettingsError(f"{key}: {number} is less than {spec.min:g}")
        if number is not None and spec.max is not None and number > spec.max:
            raise SettingsError(f"{key}: {number} is more than {spec.max:g}")
        if spec.choices and _coerce(spec, value, key) not in spec.choices:
            raise SettingsError(
                f"{key}: '{value}' is not one of {', '.join(map(str, spec.choices))}"
            )
        with self._lock:
            self._values[key] = text
            self._write()

    def _set_secret(self, key: str, owner: str, name: str, value: Any) -> None:
        """A secret from the admin panel: kept encrypted; an empty value removes it."""
        if env_name(self._app, owner, name) in self._environ:
            raise SettingsError(f"{key} is set by the environment and cannot be changed here")
        text = "" if value is None else str(value).strip()
        if "\n" in text:
            raise SettingsError(f"{key}: a value is one line")
        if text and not self._box:
            raise SettingsError(f"{key}: no secret key to keep it with; set it in the environment")
        with self._lock:
            if text:
                self._values[key] = self._seal(key, text)
            else:
                self._values.pop(key, None)
            self._write()

    def _seal(self, key: str, text: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        nonce = os.urandom(12)
        box = AESGCM(self._box).encrypt(nonce, text.encode(), key.encode())
        return "enc:" + base64.urlsafe_b64encode(nonce + box).decode().rstrip("=")

    def _open(self, key: str, stored: str) -> Any:
        """A stored secret in clear; None when it is not ours (another secret key)."""
        if not stored.startswith("enc:") or not self._box:
            return None
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        try:
            raw = base64.urlsafe_b64decode(stored[4:] + "=" * (-len(stored[4:]) % 4))
            return AESGCM(self._box).decrypt(raw[:12], raw[12:], key.encode()).decode()
        except Exception:  # noqa: BLE001 - changed, or sealed under another key
            return None

    def specs(self) -> list[tuple[str, str, str, SettingSpec]]:
        """Every declared setting: (key, owner, name, spec), by owner then name."""
        return [(k, o, n, s) for k, (o, n, s) in sorted(self._specs.items())]

    def source(self, key: str) -> str:
        """Where its value comes from: environment, store, manifest or default."""
        owner, name, _spec = self._spec(key)
        if env_name(self._app, owner, name) in self._environ:
            return "environment"
        if key in self._values:
            return "store"
        return "manifest" if key in self._instance else "default"

    def reset(self, key: str) -> None:
        """Forget the stored value: the manifest's, or the default, applies again."""
        self._spec(key)
        with self._lock:
            if self._values.pop(key, None) is not None:
                self._write()

    def forget(self, owner: str) -> None:
        """Every stored value of a module (it was uninstalled), declared or not."""
        with self._lock:
            self._values = self._read()
            gone = [k for k in self._values if k.startswith(f"{owner}.")]
            for key in gone:
                del self._values[key]
            if gone:
                self._write()

    def _write(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        body = "".join(f"{k}={v}\n" for k, v in sorted(self._values.items()))
        tmp.write_text(body, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)
        self._seen = self._stamp()

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
