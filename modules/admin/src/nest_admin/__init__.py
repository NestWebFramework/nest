"""The admin panel: one shell gathering the admin pages of every module an application includes.

Modules give their pages with ``host.admin(router)``; their manifests say how
they are listed (``admin: {title, order, role, description}``). This module
claims the panel (the pages mount under its route, at <route>/<module>),
gives every template the panel's address and the pages open to the user
(``admin_root``, ``admin_nav``), and serves the panel's front page.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from nest_auth import CurrentUser, current_user, require_user

from nest import AdminPage, ModuleHost, render

__all__ = ["visible_pages"]

router = APIRouter()


def visible_pages(request: Request, user: Any) -> list[AdminPage]:
    """The admin pages the user's roles open, in their order."""
    if user is None:
        return []
    pages = request.app.state.nest.admin_pages
    return sorted((p for p in pages if user.has(p.role)), key=lambda p: (p.order, p.title))


@router.get("/")
def home(request: Request, user: CurrentUser = Depends(require_user)):
    return render(request, "admin/home.html", pages=visible_pages(request, user))


def setup(host: ModuleHost) -> None:
    host.claim_admin()

    @host.context
    def _panel(request: Request) -> dict[str, Any]:
        root = request.app.state.nest.admin_root
        user = current_user(request)
        return {"admin_root": root, "admin_nav": visible_pages(request, user) if user else []}

    from nest_admin.settings import router as settings

    host.mount(settings)
    host.mount(router)
