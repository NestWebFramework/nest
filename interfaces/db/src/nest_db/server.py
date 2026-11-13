"""What the client-server engine providers share: building a URL, finding a driver.

A server database is configured either by one ``url`` (a secret, since it
carries the password: the usual ``DATABASE_URL`` of a cluster) or by its parts
(``host``, ``port``, ``database``, ``user`` and the secret ``password``). Either
way the provider pins the driver, so a ``postgres://`` URL from a hosting panel
still uses the driver the provider ships with.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import URL, make_url


class ConfigError(ValueError):
    pass


def require_driver(module: str, package: str) -> None:
    if importlib.util.find_spec(module) is None:
        raise ConfigError(f"the driver '{module}' is not installed; install {package}")


def build_url(
    settings: Any,
    *,
    drivername: str,
    accepted_schemes: tuple[str, ...],
    query: Mapping[str, str] | None = None,
    env_hint: str = "",
) -> URL:
    secret_url = getattr(settings, "url", None)
    if secret_url is not None:
        url = make_url(secret_url.get_secret_value())
        if url.get_backend_name() not in accepted_schemes:
            raise ConfigError(
                f"url scheme '{url.drivername}' is not one of {', '.join(accepted_schemes)}"
            )
        url = url.set(drivername=drivername)
    else:
        if not settings.database or not settings.user:
            raise ConfigError(
                "set either url, or database and user (and password)"
                + (f"; for example {env_hint}" if env_hint else "")
            )
        password = settings.password.get_secret_value() if settings.password else None
        url = URL.create(
            drivername,
            username=settings.user,
            password=password,
            host=settings.host,
            port=settings.port,
            database=settings.database,
        )
    if query:
        url = url.update_query_dict({k: v for k, v in query.items() if v}, append=False)
    return url
