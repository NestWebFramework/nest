"""Nest: a lightweight, manifest-driven host for web applications."""

from nest.bind import bound
from nest.host import AdminPage, ModuleHost, admin_url, create_app
from nest.i18n import language_name, translator
from nest.security import live, local_path
from nest.templating import is_htmx, render
from nest.toasts import toast


def _version() -> str:
    """Nest's version: nest-core's, as its package says (pyproject.toml is the one place it
    is written); "0+unknown" in a source tree no installer has seen."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("nest-core")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _version()
__all__ = [
    "AdminPage",
    "ModuleHost",
    "admin_url",
    "bound",
    "create_app",
    "is_htmx",
    "live",
    "local_path",
    "render",
    "toast",
    "language_name",
    "translator",
    "__version__",
]
