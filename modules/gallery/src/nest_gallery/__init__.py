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
    host.state["settings"] = host.settings  # the editor's upload limit
    host.admin(admin)  # an overview in the admin panel
    host.state["base"] = "" if host.route in (None, "/") else host.route
    from sqlalchemy.exc import SQLAlchemyError

    from nest_gallery import service as gallery_service

    db = host.bound("nest.db")
    gallery_service.set_default(db, host.default_language)
    try:  # what was written before the text tables: its default language's rows, once
        gallery_service.backfill(db, host.default_language)
    except SQLAlchemyError as e:
        host.log.warning(
            "gallery: the text tables are not ready (%s); migrate the database",
            e.__class__.__name__,
        )
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
        root = host.admin_root
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
        for locale in host.languages:  # each translated gallery at its address there
            if locale == host.default_language:
                continue
            done = service.translated_collections(db, locale)
            for c in service.published(db):
                row = done.get(c.id)
                if row is None:
                    continue
                shown = service.shown_photos(db, service.photos(db, c.id), locale)
                out.append(
                    {
                        "path": host.language_url(f"{base}/{c.slug}/", locale),
                        "title": row.title or c.title,
                        "subject": f"gallery.collection:{c.id}",
                        "description": row.description,
                        "kind": "gallery",
                        "group": f"Galleries · {locale.upper()}",
                        "language": locale,
                        "text": [row.description] + [i["caption"] for i in items(c, shown)],
                        "images": items(row, shown),
                        "edit": f"{root}/translations/gallery.collection/{c.id}?lang={locale}"
                        if root
                        else None,
                    }
                )
        return out

    host.answer("seo.urls", seo_pages)
    if host.settings.get("index"):
        host.mount(index_router)
    host.mount(router)
