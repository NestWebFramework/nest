"""Photo galleries and albums: their own pages, and embeds in any page via shortcodes.

Reusable by any application: include it at a route (``/galerii``) and bind
nest.db and nest.storage. With the content module, its pages show galleries
through [gallery slug=...] and [album slug=...], and the tags WordPress's
gallery plugins left behind keep working after an import.
"""

from __future__ import annotations

from nest import ModuleHost
from nest_gallery.web import index_router, items, router, shortcodes

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_gallery.admin import admin

    host.state["url"] = "" if host.route in (None, "/") else host.route
    host.admin(admin)  # an overview in the admin panel
    host.state["base"] = "" if host.route in (None, "/") else host.route
    from nest_gallery import texts

    host.template_filter("photo_alt", texts.alt)
    host.template_filter("photo_caption", texts.caption)
    host.template_filter("photo_describes", texts.describes)
    shortcodes(host)

    def seo_pages(_key: object = None) -> list[dict]:
        """The galleries (and their page of albums), each with its photos, for the sitemap."""
        from nest_gallery import service

        db = host.bound("nest.db")
        base = host.state["base"]
        root = host._nest.admin_root
        out = []
        if host.settings.get("index"):
            out.append(
                {
                    "path": f"{base}/",
                    "title": "Galleries",
                    "kind": "gallery",
                    "group": "Galleries",
                    "subject": "gallery.index",
                }
            )
        for c in service.published(db):
            shown = service.photos(db, c.id)
            out.append(
                {
                    "path": f"{base}/{c.slug}/",
                    "title": c.title,
                    "subject": f"gallery.collection:{c.id}",
                    "description": c.description,
                    "kind": "gallery",
                    "group": "Galleries",
                    "text": [c.description] + [i["caption"] for i in items(c, shown)],
                    "images": items(c, shown),
                    "edit": f"{root}/gallery/{c.id}" if root else None,
                }
            )
        return out

    host.answer("seo.urls", seo_pages)
    if host.settings.get("index"):
        host.mount(index_router)
    host.mount(router)
