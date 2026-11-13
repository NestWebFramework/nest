"""The workspace: where an application keeps what is its own at run time.

    $NEST_APP_WORKSPACE/        (default ~/.local/share/nest/<app>/)
      .env                      secrets and overrides, never committed
      data/settings.conf        runtime settings, one key=value per line
      data/secret.key           the signing key, generated in development
      data/app.db               the default SQLite database
      media/                    files the application stores

Everything instance-specific comes from here or from the environment, so the
same application moves from a laptop to a cluster by changing settings only.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from pathlib import Path


class WorkspaceError(Exception):
    pass


def resolve_workspace(app: str, environ: Mapping[str, str]) -> Path:
    if environ.get("NEST_APP_WORKSPACE"):
        root = Path(environ["NEST_APP_WORKSPACE"]).expanduser()
    else:
        base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        root = Path(base) / "nest" / app
    for sub in (root, root / "data", root / "media"):
        sub.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()


def read_dotenv(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines; ``#`` comments; optional quotes. Nothing is expanded."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def environment(workspace: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """The workspace ``.env`` under the process environment (the process wins)."""
    return {**read_dotenv(workspace / ".env"), **environ}


def is_production(environ: Mapping[str, str]) -> bool:
    return environ.get("NEST_ENV", "development").lower() == "production"


def secret_key(workspace: Path, environ: Mapping[str, str]) -> str:
    """The key that signs cookies. Production must set it; development generates one."""
    if environ.get("NEST_SECRET_KEY"):
        key = environ["NEST_SECRET_KEY"]
        if len(key) < 32:
            raise WorkspaceError("NEST_SECRET_KEY must be at least 32 characters")
        return key
    if is_production(environ):
        raise WorkspaceError("NEST_SECRET_KEY must be set when NEST_ENV=production")
    path = workspace / "data" / "secret.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return key
