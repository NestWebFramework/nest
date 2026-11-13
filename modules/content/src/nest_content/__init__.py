"""Content: typed entries, taxonomies, menus and media; the CMS of Nest.

Content types are declared in YAML (any manifest, the application's last);
entries are found by their stored path, so a moved site keeps its addresses;
bodies are sanitized HTML with shortcodes; editors work under /admin/content.
"""

from __future__ import annotations

from nest import ModuleHost
from nest.host import HostError
from nest_content.html import shortcode
from nest_content.service import KIND, EntryData
from nest_content.types import Registry
from nest_content.web import router, serve

__all__ = ["KIND", "EntryData", "Registry", "shortcode"]


def setup(host: ModuleHost) -> None:
    if host.route != "/":
        raise HostError("content serves whole-site paths; include it with route: /")
    registry = Registry.from_sections(host.sections("content_types"), host.sections("taxonomies"))
    host.state.update(types=registry, settings=host.settings)
    db = host.bound("nest.db")

    @host.context
    def _content(request):
        from nest_content import service

        return {"menu": lambda slug: service.menu_tree(db, slug), "content_types": registry.types}

    host.mount(router)
    host.fallback(serve)
