"""SQLite FTS5 as ``nest.search``."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from nest_search import MARK_END, MARK_START, Document, Hit, terms_of

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(
    kind UNINDEXED, doc_id UNINDEXED, scope UNINDEXED, url UNINDEXED,
    title, body,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def match_expression(text: str, *, column: str | None = None) -> str | None:
    """Every word must match; the last may be the start of a word. No user syntax."""
    words = terms_of(text)
    if not words:
        return None
    quoted = [f'"{w}"' for w in words]
    quoted[-1] += "*"
    expr = " AND ".join(quoted)
    return f"{column} : ({expr})" if column else expr


class SqliteSearch:
    def __init__(self, path: str, title_weight: float = 10.0):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._weight = float(title_weight)
        self._lock = threading.Lock()

    def index(self, documents: list[Document]) -> None:
        with self._lock, self._conn:
            for d in documents:
                self._conn.execute(
                    "DELETE FROM documents WHERE kind = ? AND doc_id = ?", (d.kind, d.id)
                )
                self._conn.execute(
                    "INSERT INTO documents (kind, doc_id, scope, url, title, body) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (d.kind, d.id, d.scope, d.url, d.title, d.body),
                )

    def remove(self, kind: str, ids: list[str]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM documents WHERE kind = ? AND doc_id = ?", [(kind, i) for i in ids]
            )

    def clear(self, kind: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM documents WHERE kind = ?", (kind,))

    def _where(self, match: str, kind: str | None, scope: str | None) -> tuple[str, list[Any]]:
        sql, params = "documents MATCH ?", [match]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        return sql, params

    def _hits(self, sql: str, params: list[Any]) -> list[Hit]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            Hit(kind=k, id=i, scope=s, url=u, title=t, snippet=snip or "", score=-rank)
            for k, i, s, u, t, snip, rank in rows
        ]

    def query(
        self,
        text: str,
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Hit]:
        match = match_expression(text)
        if match is None:
            return []
        where, params = self._where(match, kind, scope)
        sql = (
            "SELECT kind, doc_id, scope, url, title, "
            f"snippet(documents, 5, '{MARK_START}', '{MARK_END}', '…', 16), "
            "bm25(documents, 0, 0, 0, 0, ?, 1.0) AS rank "
            f"FROM documents WHERE {where} ORDER BY rank LIMIT ? OFFSET ?"
        )
        return self._hits(sql, [self._weight, *params, max(1, min(limit, 200)), max(0, offset)])

    def count(self, text: str, *, kind: str | None = None, scope: str | None = None) -> int:
        match = match_expression(text)
        if match is None:
            return 0
        where, params = self._where(match, kind, scope)
        with self._lock:
            return self._conn.execute(
                f"SELECT count(*) FROM documents WHERE {where}", params
            ).fetchone()[0]

    def suggest(
        self, prefix: str, *, kind: str | None = None, scope: str | None = None, limit: int = 8
    ) -> list[Hit]:
        match = match_expression(prefix, column="title")
        if match is None:
            return []
        where, params = self._where(match, kind, scope)
        sql = (
            "SELECT kind, doc_id, scope, url, title, '', bm25(documents) AS rank "
            f"FROM documents WHERE {where} ORDER BY length(title), rank LIMIT ?"
        )
        return self._hits(sql, [*params, max(1, min(limit, 50))])

    def close(self) -> None:
        self._conn.close()


def create(settings: Any, context: Any) -> SqliteSearch:
    path = settings.path
    if path != ":memory:":
        target = context.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        path = str(target)
    return SqliteSearch(path, settings.title_weight)
