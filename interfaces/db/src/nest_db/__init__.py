"""The ``nest.db`` interface: one way to reach a relational database.

Modules code against :class:`Database` and SQLAlchemy sessions, never against
an engine. The application binds ``nest.db`` to an engine provider —
``db-sqlite``, ``db-postgres``, ``db-mariadb`` — and changing databases is a
change of that binding and its settings, not of module code.

What stays the same across engines lives here:

* :class:`Database`, the Protocol every provider is checked against;
* :class:`SqlDatabase`, the wrapper each provider builds on (it only has to
  bring a configured SQLAlchemy engine);
* :func:`model_base`, a declarative base per module with a naming convention
  for constraints (so migrations read the same on every engine) and table
  names prefixed by the module, so modules can never collide.

What differs — the driver, the URL, pooling, session set-up, pragmas — is the
provider's business.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import Engine, MetaData, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

__all__ = ["Database", "SqlDatabase", "model_base", "NAMING_CONVENTION"]

# Constraint names chosen by convention, not by the engine, so a migration
# written against SQLite drops the same constraint on PostgreSQL or MariaDB.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


@runtime_checkable
class Database(Protocol):
    def engine(self) -> Engine:
        """The SQLAlchemy engine, for Core queries and migrations."""
        ...

    def session(self) -> Session:
        """A new ORM session: ``with db.session() as s, s.begin(): ...``."""
        ...

    def dialect(self) -> str:
        """``sqlite``, ``postgresql`` or ``mariadb``: for the rare engine-specific path."""
        ...

    def capabilities(self) -> frozenset[str]:
        """What the engine offers beyond plain SQL: ``json``, ``fts``, ``returning``, ``schemas``."""
        ...

    def ping(self) -> bool:
        """Whether the database answers now. The health page calls it."""
        ...

    def dispose(self) -> None:
        """Close every pooled connection. The host calls it at shutdown."""
        ...


class GatedSession(Session):
    """A session that holds a gate while it is open, so only so many threads work in the
    database at once. SQLite gives its work back to Python between rows; with many
    threads asking at the same time, handing it round costs far more than the work
    itself (ten threads read 45 times slower than one waiting its turn). The gate is
    re-entrant: a session opened inside another, on the same thread, does not wait for
    itself."""

    def __init__(self, *args: Any, gate: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._gate = gate
        self._holding = 0

    def __enter__(self) -> GatedSession:
        if self._gate is not None:
            self._gate.acquire()
            self._holding += 1
        return super().__enter__()

    def close(self) -> None:
        try:
            super().close()
        finally:
            while self._holding:
                self._holding -= 1
                self._gate.release()


class SqlDatabase:
    """The engine-independent half of every provider: give it an engine; ``gate`` (a
    re-entrant lock) lets one thread at a time into the database (SQLite's provider
    gives one; a database server needs none)."""

    def __init__(
        self, engine: Engine, capabilities: frozenset[str] = frozenset(), *, gate: Any = None
    ):
        self._engine = engine
        self._capabilities = frozenset(capabilities)
        if gate is not None:
            self._sessions = sessionmaker(
                engine, expire_on_commit=False, class_=GatedSession, gate=gate
            )
        else:
            self._sessions = sessionmaker(engine, expire_on_commit=False)

    def engine(self) -> Engine:
        return self._engine

    def session(self) -> Session:
        return self._sessions()

    def dialect(self) -> str:
        return self._engine.dialect.name

    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def ping(self) -> bool:
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - "does not answer" is the answer
            return False

    def dispose(self) -> None:
        self._engine.dispose()

    def __repr__(self) -> str:
        url = self._engine.url.render_as_string(hide_password=True)
        return f"<{type(self).__name__} {url}>"


def model_base(module: str) -> type[DeclarativeBase]:
    """A declarative base for one module's models.

    Every table it maps must be named ``<module>_<name>`` (``glossary_term``),
    which keeps two modules' tables apart in one database.
    """
    prefix = re.sub(r"[^a-z0-9]+", "_", module.lower()).strip("_") + "_"
    convention = MetaData(naming_convention=NAMING_CONVENTION)

    class Base(DeclarativeBase):
        metadata = convention
        table_prefix = prefix

        def __init_subclass__(cls, **kwargs: object) -> None:
            name = cls.__dict__.get("__tablename__")
            if name is not None and not str(name).startswith(prefix):
                raise TypeError(
                    f"{cls.__name__}: table '{name}' must be named '{prefix}…' "
                    f"(tables belong to the module that owns them)"
                )
            super().__init_subclass__(**kwargs)

    Base.__name__ = Base.__qualname__ = f"{prefix.rstrip('_').title().replace('_', '')}Base"
    return Base
