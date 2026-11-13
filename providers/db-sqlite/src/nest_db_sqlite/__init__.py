"""SQLite as ``nest.db``."""

from __future__ import annotations

import sqlite3
from typing import Any

from nest_db import SqlDatabase
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

CAPABILITIES = frozenset({"json", "fts", "returning"})


def create(settings: Any, context: Any) -> SqlDatabase:
    if settings.path == ":memory:":
        # One shared connection, or every session would see an empty database.
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    else:
        path = context.path(settings.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}")

    # The values come from closed choices, so they are safe to put in a PRAGMA.
    journal, sync, timeout = (
        settings.journal_mode,
        settings.synchronous,
        int(settings.busy_timeout_ms),
    )

    @event.listens_for(engine, "connect")
    def _pragmas(conn: sqlite3.Connection, _record: Any) -> None:
        cur = conn.cursor()
        if settings.path != ":memory:":
            cur.execute(f"PRAGMA journal_mode={journal}")
        cur.execute(f"PRAGMA synchronous={sync}")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA busy_timeout={timeout}")
        cur.close()

    caps = CAPABILITIES if sqlite3.sqlite_version_info >= (3, 35) else CAPABILITIES - {"returning"}
    return SqlDatabase(engine, caps)
