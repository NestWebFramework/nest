"""Failed sign-ins per (email, address), counted where every worker sees them.

Under ``nest serve`` an application runs as several processes, and a count kept in one
process's memory would let a guesser try (limit x workers) passwords. So the count lives
in the application's shared cache when it binds one every worker shares (redis), and
otherwise in its database, which every worker shares by nature. Only a failure writes;
a sign-in reads one indexed count.

The key is hashed: the table and the cache hold no email and no address.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import random
from datetime import timedelta
from typing import Any

import anyio.from_thread
from sqlalchemy import delete, func, select

from nest_auth.models import Failure, utcnow

log = logging.getLogger("nest.auth")


KEEP_S = 2 * 86400  # failures older than this go (longer than any throttle's window)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class DbThrottle:
    """A sliding window over the failures in the auth_failure table."""

    def __init__(self, db: Any, limit: int, window_s: int):
        self.db, self.limit, self.window = db, limit, window_s

    def _since(self):
        return utcnow() - timedelta(seconds=self.window)

    def blocked(self, key: str) -> bool:
        with self.db.session() as s:
            count = s.scalar(
                select(func.count())
                .select_from(Failure)
                .where(Failure.key == _digest(key), Failure.at > self._since())
            )
        return (count or 0) >= self.limit

    def fail(self, key: str) -> None:
        with self.db.session() as s, s.begin():
            s.add(Failure(key=_digest(key), at=utcnow()))
            if random.random() < 0.05:  # now and then, forget the old failures  # noqa: S311
                # every throttle shares the table: past the longest window any keeps (a day's
                # new accounts), not this one's, or a short one would wipe a long one's counts
                keep = max(self.window, KEEP_S)
                s.execute(delete(Failure).where(Failure.at <= utcnow() - timedelta(seconds=keep)))

    def clear(self, key: str) -> None:
        with self.db.session() as s, s.begin():
            s.execute(delete(Failure).where(Failure.key == _digest(key)))


class CacheThrottle:
    """A counter in the shared cache that expires a window after the first failure.

    The sign-in handlers are synchronous (they run in the worker's thread pool), the cache
    is asynchronous: each call goes back to the worker's event loop. When the cache cannot
    be reached, the database counts instead, so the limit never silently disappears."""

    def __init__(self, cache: Any, fallback: DbThrottle):
        self.cache, self.fallback = cache, fallback
        self.limit, self.window = fallback.limit, fallback.window

    def _name(self, key: str) -> str:
        return f"auth:fail:{_digest(key)}"

    def _call(self, fn: Any, *args: Any) -> Any:
        return anyio.from_thread.run(fn, *args)

    def blocked(self, key: str) -> bool:
        try:
            return int(self._call(self.cache.get, self._name(key)) or 0) >= self.limit
        except Exception:  # noqa: BLE001 - the cache is down: the database answers
            log.warning("sign-in limits: the cache did not answer; using the database")
            return self.fallback.blocked(key)

    def fail(self, key: str) -> None:
        try:
            self._call(self.cache.incr, self._name(key), 1, self.window)
        except Exception:  # noqa: BLE001
            self.fallback.fail(key)

    def clear(self, key: str) -> None:
        with contextlib.suppress(Exception):
            self._call(self.cache.delete, self._name(key))
        self.fallback.clear(key)


def make_throttle(db: Any, cache: Any, limit: int, window_s: int) -> DbThrottle | CacheThrottle:
    """The shared cache's counter when there is one every worker shares, else the database."""
    on_db = DbThrottle(db, limit, window_s)
    return CacheThrottle(cache, on_db) if cache is not None else on_db
