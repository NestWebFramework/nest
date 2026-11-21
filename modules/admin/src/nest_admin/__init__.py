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

__all__ = ["menu", "settings_owners", "tabs", "visible_pages"]

router = APIRouter()


def visible_pages(request: Request, user: Any) -> list[AdminPage]:
    """The admin pages the user's roles open, in their order."""
    if user is None:
        return []
    pages = request.app.state.nest.admin_pages
    return sorted((p for p in pages if user.has(p.role)), key=lambda p: (p.order, p.title))


SITE = "Site"  # the panel's own pages' group (settings, modules, languages, themes)


def settings_owners(request: Request) -> set[str]:
    """The modules with settings the admin panel shows to change."""
    nest = request.app.state.nest
    return {owner for _k, owner, _n, spec in nest.settings.specs() if spec.editable}


def menu(request: Request, user: Any) -> list[dict[str, Any]]:
    """The admin panel's menu: links of their own, and groups of links (a group open when the
    page shown is in it). Groups come in the application's order (application.admin_menu),
    then by their first page's order; the panel's own pages are in the Site group."""
    nest = request.app.state.nest
    root = nest.admin_root or ""
    path = request.url.path
    links: list[tuple[str, dict[str, Any]]] = []
    from nest_admin.settings import settings_roles

    owners = settings_owners(request)
    roles = {r for m, r in settings_roles(nest).items() if m in owners}
    if not user.has("admin") and any(user.has(r) for r in roles):  # a game master: the rules
        links.append(
            (
                "",
                {
                    "href": root + "/settings",
                    "title": "Settings",
                    "here": path.startswith(root + "/settings"),
                    "own": True,
                },
            )
        )
    if user.has("admin"):
        for href, title in (
            ("/settings", "Settings"),
            ("/modules", "Modules"),
            ("/languages", "Languages"),
            ("/themes", "Themes"),
        ):
            links.append(
                (
                    SITE,
                    {
                        "href": root + href,
                        "title": title,
                        "here": path.startswith(root + href),
                        "own": True,
                    },
                )
            )
    for p in visible_pages(request, user):
        here = path.startswith(p.base) or path.rstrip("/") == f"{root}/settings/{p.module}"
        links.append(
            (p.group, {"href": p.base + "/", "title": p.title, "here": here, "own": False})
        )
    ordered = [title for title, _m in nest.admin_menu]
    out: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for group, link in links:
        if not group:
            out.append({"title": "", "links": [link], "open": link["here"]})
            continue
        if group not in groups:
            groups[group] = {"title": group, "links": [], "open": False}
            out.append(groups[group])
        groups[group]["links"].append(link)
        groups[group]["open"] = groups[group]["open"] or link["here"]
    first = {id(g): i for i, g in enumerate(out)}  # the order they came in: their pages'
    site_last = lambda g: g["title"] == SITE  # noqa: E731 - the panel's own pages, at the end
    out.sort(
        key=lambda g: (
            site_last(g),
            ordered.index(g["title"]) if g["title"] in ordered else len(ordered),
            first[id(g)],
        )
    )
    return out


def tabs(request: Request, user: Any) -> list[dict[str, Any]]:
    """On a module's admin pages: its pages, and its settings, when it has settings this user
    may change."""
    nest = request.app.state.nest
    root = nest.admin_root or ""
    path = request.url.path.rstrip("/")
    owners = settings_owners(request)
    from nest_admin.settings import settings_roles

    roles = settings_roles(nest)
    for p in visible_pages(request, user):
        on_page, on_settings = path.startswith(p.base), path == f"{root}/settings/{p.module}"
        role = roles.get(p.module)
        may = user.has("admin") or (role and user.has(role))
        if (on_page or on_settings) and p.module in owners and may:
            return [
                {"href": p.base + "/", "title": p.title, "here": on_page},
                {"href": f"{root}/settings/{p.module}", "title": "Settings", "here": on_settings},
            ]
    return []


@router.get("/")
def home(request: Request, user: CurrentUser = Depends(require_user)):
    waiting: dict[str, int] = {}  # what waits for someone, by module ("admin.waiting")
    for answer in request.app.state.nest.gather("admin.waiting"):
        if isinstance(answer, dict):
            waiting.update({k: int(v) for k, v in answer.items() if v})
    return render(request, "admin/home.html", pages=visible_pages(request, user), waiting=waiting)


def setup(host: ModuleHost) -> None:
    host.claim_admin()

    @host.context
    def _panel(request: Request) -> dict[str, Any]:
        root = request.app.state.nest.admin_root
        user = current_user(request)
        return {
            "admin_root": root,
            "admin_nav": visible_pages(request, user) if user else [],
            "admin_menu": menu(request, user) if user else [],
            "admin_tabs": tabs(request, user) if user else [],
        }

    from nest_admin.languages import router as languages
    from nest_admin.modules import router as modules
    from nest_admin.settings import router as settings
    from nest_admin.themes import ThemePreview
    from nest_admin.themes import router as themes

    host.state["sign"] = host.sign  # the theme preview's cookie
    host.add_middleware(ThemePreview, unsign=host.unsign)

    @host.context
    def _preview(request: Request) -> dict[str, Any]:
        return {"theme_preview": getattr(request.state, "theme_preview", None)}

    host.mount(settings)
    host.mount(modules)
    host.mount(themes)
    host.mount(languages)
    host.mount(router)
