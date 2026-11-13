"""Content: typed entries, taxonomies, menus and media; the CMS of Nest.

Content types are declared in YAML (any manifest, the application's last);
entries are found by their stored path, so a moved site keeps its addresses;
bodies are sanitized HTML with shortcodes; editors work under /admin/content.
"""

from __future__ import annotations

from nest import ModuleHost
from nest.host import HostError
from nest_content.service import KIND, EntryData
from nest_content.types import Registry
from nest_content.web import Context, catlist, router, serve, wp_gallery

__all__ = ["KIND", "Context", "EntryData", "Registry"]


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

    from nest_content import service as _service

    def wordpress_post(legacy_id: int) -> dict | None:
        e = _service.entry_by_legacy(db, int(legacy_id))
        if e is None:
            return None
        return {"subject": f"content.entry:{e.id}", "url": e.path, "title": e.title}

    host.answer("wordpress.post", wordpress_post)
    host.shortcode("catlist", catlist)
    if not host.has_module("gallery"):
        # WordPress's own [gallery ids="..."]; the gallery module answers [gallery] when present.
        host.shortcode("gallery", wp_gallery)
    host.mount(router)
    host.fallback(serve, priority=10)
