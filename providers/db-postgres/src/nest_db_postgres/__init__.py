"""PostgreSQL as ``nest.db``."""

from __future__ import annotations

from typing import Any

from nest_db import SqlDatabase, build_url, require_driver
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

CAPABILITIES = frozenset({"json", "jsonb", "fts", "returning", "schemas"})


def url_for(settings: Any, context: Any) -> URL:
    return build_url(
        settings,
        drivername="postgresql+psycopg",
        accepted_schemes=("postgresql", "postgres"),
        query={"sslmode": settings.sslmode},
        env_hint=f"NEST_{context.app.upper().replace('-', '_')}__DB_POSTGRES__URL",
    )


def connect_args(settings: Any, context: Any) -> dict[str, Any]:
    options = "-c timezone=UTC"
    if settings.statement_timeout_ms:
        options += f" -c statement_timeout={int(settings.statement_timeout_ms)}"
    return {"application_name": context.app[:63], "options": options}


def create(settings: Any, context: Any) -> SqlDatabase:
    url = url_for(settings, context)
    require_driver("psycopg", "nest-db-postgres (psycopg[binary])")
    engine = create_engine(
        url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout,
        pool_pre_ping=True,
        connect_args=connect_args(settings, context),
    )
    return SqlDatabase(engine, CAPABILITIES)
