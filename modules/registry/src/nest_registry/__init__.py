"""A registry of Nest packages: a Python package index (uv, pip) and a catalog of what each
package is for Nest, as registry.nest-framework.org runs it (see module.yml)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from nest_auth import CurrentUser, require_role

from nest import ModuleHost, render

__all__: list[str] = []

admin = APIRouter()
administrators = require_role("admin")


@admin.get("/")
def overview(request: Request, user: CurrentUser = Depends(administrators)):
    from nest.host import module_state  # noqa: PLC0415
    from nest_registry import service  # noqa: PLC0415

    state = module_state(request, "registry")
    return render(
        request,
        "registry/admin.html",
        items=service.catalog(state["db"]),
        counts=service.counts(state["db"]),
        namespaces=service.namespaces(state["db"]),
        publishers=str(state["settings"].get("publishers")),
        base=state["base"],
    )


def setup(host: ModuleHost) -> None:
    from nest_registry.web import api, pages  # noqa: PLC0415

    host.state.update(
        db=host.bound("nest.db"),
        storage=host.bound("nest.storage"),
        settings=host.settings,
        base="" if host.route in (None, "/") else host.route,
    )
    host.mount(api, csrf=False)  # tokens on every request, never cookies
    host.mount(pages)
    host.admin(admin)
