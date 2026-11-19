"""SQLite as ``nest.db``."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from nest_db import SqlDatabase
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

CAPABILITIES = frozenset({"json", "fts", "returning"})

# One gate for every SQLite database of the process: what makes many threads slow is
# Python's lock, which they all share, so they take their turns in all databases at once.
GATE = threading.RLock()


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
    return SqlDatabase(engine, caps, gate=GATE if settings.one_at_a_time else None)
