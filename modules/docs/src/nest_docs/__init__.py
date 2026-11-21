"""Documentation as a site: a tree of Markdown pages, a menu, search, pictures, and a
reference page for every package installed, made from its manifest.

The tree is a folder (the ``tree`` setting): ``site.yml`` gives its title and sections,
each section its pages in order (``start/install`` is ``start/install.md``); a section
with ``reference: modules`` (or themes, providers, interfaces) lists one made page per
package of that kind. ``index.md`` is the documentation's front page, ``landing.md`` the
site's home when ``home`` is on. Pages link to each other by their files (``install.md``)
and show pictures beside them; ``nest docs check APP`` says which links lead nowhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nest import ModuleHost
from nest_docs.markdown import render
from nest_docs.tree import Tree

__all__ = ["Tree", "render"]


def tree_of(host: ModuleHost) -> Tree:
    from nest_docs.reference import collect

    root = Path(str(host.settings.get("tree") or "docs"))
    if not root.is_absolute():
        root = Path(host.app_root) / root
    base = "" if host.route in (None, "/") else host.route.rstrip("/")
    refs = collect(Path(host.app_root)) if host.settings.get("reference") else []
    return Tree(root, base, reload=bool(host.settings.get("reload")), reference=refs)


def setup(host: ModuleHost) -> None:
    from nest_docs.web import home_router, router

    tree = tree_of(host)
    host.state.update(
        tree=tree, edit_url=host.live("edit_url", lambda v: str(v or "")), indexed=False
    )

    def nav() -> list[tuple[str, str]]:
        spec = str(host.settings.get("nav") or "")
        return [
            (label.strip(), href.strip())
            for part in spec.split(";")
            if "=" in part
            for label, href in [part.split("=", 1)]
        ]

    @host.context
    def _docs(request: Any) -> dict[str, Any]:
        return {"docs_tree": tree, "docs_nav": nav()}

    def seo_pages(_key: object = None) -> list[dict]:
        out = []
        for e, page in tree.all_pages():
            out.append(
                {
                    "path": tree.url(e.key),
                    "title": page.title or e.title,
                    "kind": "docs",
                    "group": e.section or "Documentation",
                    "subject": f"docs.page:{e.key}",
                    "description": str(page.meta.get("description") or ""),
                }
            )
        return out

    host.answer("seo.urls", seo_pages)
    if host.settings.get("home"):
        host.serve_at_root(home_router)
    host.mount(router)
