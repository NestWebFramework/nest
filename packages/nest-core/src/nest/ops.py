"""Running an application for real: is it ready, and its backups.

``nest check APP``    what production needs, each item ok, a warning, or a failure
``nest backup APP``   the workspace in one archive: each SQLite database copied while
                      the site runs (SQLite's online backup), the stored files, the
                      settings. Not the .env (its secrets belong to the server, not
                      to every copy of a backup) and not the pictures media made at
                      other widths (they are made again when asked for).
``nest restore APP ARCHIVE``  back into an empty workspace (or --force over one), with
                      the application stopped.

A database on a server (Postgres, MariaDB) is not in the archive: its own tools back it
up (pg_dump, mariadb-dump), and the archive says so.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SKIP_DIRS = {"backups", "_sized", "__pycache__"}
SKIP_FILES = {".env"}
FORMAT = 1


@dataclass
class Finding:
    level: str  # "ok", "warn", "fail"
    text: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        self.findings.append(Finding(level, text))

    @property
    def failed(self) -> bool:
        return any(f.level == "fail" for f in self.findings)


# --- what the application is made of -------------------------------------------------


def _sqlite_files(nest: Any) -> list[Path]:
    out = []
    for provider in nest.bindings.providers():
        engine = getattr(provider.impl, "engine", None)
        if not callable(engine):
            continue
        url = engine().url
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            out.append(Path(url.database).resolve())
    return out


def _server_databases(nest: Any) -> list[str]:
    out = []
    for provider in nest.bindings.providers():
        engine = getattr(provider.impl, "engine", None)
        if callable(engine) and engine().url.get_backend_name() != "sqlite":
            out.append(provider.name)
    return out


def _storage_roots(nest: Any) -> list[Path]:
    return [
        Path(p.impl.root).resolve()
        for p in nest.bindings.providers()
        if isinstance(getattr(p.impl, "root", None), Path)
    ]


def _backups(workspace: Path) -> list[Path]:
    folder = workspace / "backups"
    return sorted(folder.glob("*.tar.gz")) if folder.is_dir() else []


# --- check ---------------------------------------------------------------------------


def check(nest: Any) -> Report:
    """What running ``nest`` in production needs, and what it lacks."""
    r = Report()
    env = nest.environ
    if nest.production:
        r.add("ok", "NEST_ENV=production: secure cookies, HSTS, no API docs")
    else:
        r.add("fail", "NEST_ENV is not production (cookies are not secure, the API docs are open)")
    key = env.get("NEST_SECRET_KEY", "")
    if len(key) >= 32:
        r.add("ok", "NEST_SECRET_KEY is set")
    else:
        r.add(
            "fail", "NEST_SECRET_KEY is not set (32 characters or more), in the environment or .env"
        )
    hosts = [h for h in env.get("NEST_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if hosts:
        r.add("ok", f"answers only for: {', '.join(h.strip() for h in hosts)}")
    else:
        r.add("warn", "NEST_ALLOWED_HOSTS is not set: it answers whatever host it is asked for")
    if "content" in nest.module_state:
        site = str(nest.settings.get("content.site_url") or "")
        if site.startswith("https://"):
            r.add("ok", f"public address: {site}")
        else:
            r.add(
                "warn",
                "content.site_url is not an https address: the sitemap and shared links "
                "take the address of each request",
            )
    try:
        probe = nest.workspace / ".write-check"
        probe.write_text("ok")
        probe.unlink()
        r.add("ok", f"workspace {nest.workspace} is writable")
    except OSError as e:
        r.add("fail", f"workspace {nest.workspace} is not writable: {e}")
    free = shutil.disk_usage(nest.workspace).free / 2**30
    r.add("ok" if free >= 2 else "warn", f"{free:.1f} GB free beside the workspace")
    for path in _sqlite_files(nest):
        with sqlite3.connect(path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            ok = conn.execute("PRAGMA quick_check").fetchone()[0]
        r.add("ok" if mode == "wal" else "warn", f"SQLite {path.name}: journal {mode}")
        r.add("ok" if ok == "ok" else "fail", f"SQLite {path.name}: integrity {ok}")
    for name in _server_databases(nest):
        r.add("ok", f"{name}: back it up with its own tools (not in nest backup)")
    if "auth" in {u.name for u in nest.plan.units}:
        from nest_auth.sessions import list_accounts  # noqa: PLC0415

        accounts, _total = list_accounts(nest.bindings.get("nest.db"), limit=10000)
        admins = sum(1 for a in accounts if "admin" in a.roles and getattr(a, "active", True))
        r.add(
            "ok" if admins else "warn",
            f"{admins} administrator account(s)"
            + ("" if admins else ": nest auth create-user APP EMAIL --role admin"),
        )
    found = _backups(nest.workspace)
    if not found:
        r.add("warn", "no backup yet (nest backup APP; run it daily, keep copies off this server)")
    else:
        age = (datetime.now() - datetime.fromtimestamp(found[-1].stat().st_mtime)).days
        r.add("ok" if age <= 2 else "warn", f"last backup {found[-1].name}, {age} day(s) ago")
    return r


# --- backup ----------------------------------------------------------------------------


def _skip(path: Path, databases: set[Path]) -> bool:
    if path.name in SKIP_FILES or any(part in SKIP_DIRS for part in path.parts):
        return True
    if path.name.endswith(("-wal", "-shm", "-journal")):  # in the database's copy already
        return True
    return path.name.startswith(".upload-")


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def backup(nest: Any, target: Path | None = None, keep: int = 0) -> Path:
    """The workspace in one archive; returns where it is."""
    workspace = nest.workspace.resolve()
    folder = (target or workspace / "backups").expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = folder / f"{nest.name}-{stamp}.tar.gz"
    # every SQLite file of the workspace (the bound database, the search index...)
    databases = set(_sqlite_files(nest)) | {
        p.resolve()
        for p in workspace.rglob("*")
        if p.is_file() and not _skip(p.relative_to(workspace), set()) and _is_sqlite(p)
    }
    outside = [r for r in _storage_roots(nest) if not r.is_relative_to(workspace)]
    meta = {
        "format": FORMAT,
        "application": nest.name,
        "made": stamp,
        "databases": [
            str(d.relative_to(workspace)) for d in databases if d.is_relative_to(workspace)
        ],
        "storage_outside": [str(r) for r in outside],
        "not_included": [".env", "media/_sized"] + _server_databases(nest),
    }
    partial = archive.with_suffix(".partial")
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(partial, "w:gz") as tar:
        for db in databases:  # a consistent copy, taken while the site runs
            copy = Path(tmp) / db.name
            with sqlite3.connect(db) as source, sqlite3.connect(copy) as dest:
                source.backup(dest)
            name = (
                db.relative_to(workspace) if db.is_relative_to(workspace) else Path("_db") / db.name
            )
            tar.add(copy, arcname=f"workspace/{name}")
        for root in [workspace, *outside]:
            prefix = "workspace" if root == workspace else f"_storage/{outside.index(root)}"
            for path in sorted(root.rglob("*")):
                rel = path.relative_to(root)
                if path.resolve() in databases:
                    continue  # its consistent copy is in already
                if path.is_file() and not path.is_symlink() and not _skip(rel, databases):
                    if path.resolve().is_relative_to(folder):
                        continue  # the backups themselves
                    tar.add(path, arcname=f"{prefix}/{rel}")
        info = Path(tmp) / "backup.json"
        info.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tar.add(info, arcname="backup.json")
    os.replace(partial, archive)
    if keep > 0:
        mine = sorted(folder.glob(f"{nest.name}-*.tar.gz"))
        for old in mine[:-keep]:
            old.unlink()
    return archive


# --- restore ---------------------------------------------------------------------------


class RestoreError(Exception):
    pass


def restore(app: str, archive: Path, workspace: Path, *, force: bool = False) -> dict[str, Any]:
    """An archive back into ``workspace`` (the application stopped). Returns its backup.json."""
    with tarfile.open(archive, "r:gz") as tar:
        try:
            meta = json.load(tar.extractfile("backup.json"))  # type: ignore[arg-type]
        except KeyError:
            raise RestoreError(f"{archive.name} is not a nest backup (no backup.json)") from None
        if meta.get("application") != app:
            raise RestoreError(
                f"{archive.name} is a backup of {meta.get('application')!r}, not {app!r}"
            )
        data = workspace / "data"
        if data.exists() and any(data.iterdir()) and not force:
            raise RestoreError(
                f"{workspace} already holds data; stop the application and use --force"
            )
        members = []
        for m in tar.getmembers():
            if not m.name.startswith("workspace/") or not (m.isfile() or m.isdir()):
                continue
            m.name = m.name.removeprefix("workspace/")
            members.append(m)
        workspace.mkdir(parents=True, exist_ok=True)
        for db in meta.get("databases", []):  # a stale WAL must not be replayed over the copy
            for suffix in ("-wal", "-shm"):
                (workspace / (db + suffix)).unlink(missing_ok=True)
        tar.extractall(workspace, members=members, filter="data")
    return meta
