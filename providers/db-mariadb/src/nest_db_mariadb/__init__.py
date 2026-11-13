"""MariaDB (and MySQL) as ``nest.db``."""

from __future__ import annotations

from typing import Any

from nest_db import SqlDatabase
from nest_db.server import build_url, require_driver
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

CAPABILITIES = frozenset({"json", "fts"})

SQL_MODE = (
    "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
    "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"
)


def url_for(settings: Any, context: Any) -> URL:
    return build_url(
        settings,
        drivername=f"{settings.flavour}+pymysql",
        accepted_schemes=("mariadb", "mysql"),
        query={"charset": "utf8mb4"},
        env_hint=f"NEST_{context.app.upper().replace('-', '_')}__DB_MARIADB__URL",
    )


def connect_args(settings: Any, context: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "init_command": f"SET SESSION time_zone='+00:00', sql_mode='{SQL_MODE}'",
        "program_name": context.app,
    }
    if settings.ssl_ca:
        args["ssl"] = {"ca": str(context.path(settings.ssl_ca))}
    return args


def create(settings: Any, context: Any) -> SqlDatabase:
    url = url_for(settings, context)
    require_driver("pymysql", "nest-db-mariadb (pymysql)")
    engine = create_engine(
        url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_recycle=settings.pool_recycle,
        pool_pre_ping=True,
        connect_args=connect_args(settings, context),
    )
    return SqlDatabase(engine, CAPABILITIES)
