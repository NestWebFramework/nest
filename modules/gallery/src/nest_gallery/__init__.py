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

    def spotlight(q: object) -> dict | None:
        """An article's pictures shown as the gallery shows its photos (spotlight.py):
        {"html": ..., "all": every picture opens large, "viewer": the lightbox's address}
        -> {"html": ..., "used": ...}."""
        from nest_gallery import spotlight as spot

        if not isinstance(q, dict):
            return None
        return spot.transform(
            str(q.get("html") or ""), bool(q.get("all")), str(q.get("viewer") or "")
        )

    host.answer("gallery.spotlight", spotlight)

    def photos_of_the_day(n: int = 8, locale: str = "") -> list[dict]:
        """``gallery_photos(8)`` in a template: some photos of the published albums, others
        each day (a home page's strip), each with its album's title and address."""
        import hashlib  # noqa: PLC0415
        from datetime import date  # noqa: PLC0415

        from nest_gallery import service  # noqa: PLC0415

        db = host.bound("nest.db")
        albums = {c.id: c for c in service.published(db)}
        titles = service.translated_collections(db, locale) if locale else {}
        pool = [
            (p, albums[p.collection_id])
            for c in albums.values()
            for p in service.photos(db, c.id)
            if p.key and not p.key.lower().endswith((".gif", ".svg"))
        ]
        if not pool:
            return []
        day = date.today().isoformat()
        pool.sort(key=lambda pc: hashlib.sha256(f"{day}|{pc[0].id}".encode()).digest())
        out, seen = [], set()
        for p, c in pool:  # one photo per album first, so the strip shows many places
            if c.id in seen:
                continue
            seen.add(c.id)
            out.append(
                {
                    "key": p.key,
                    "alt": p.alt or p.caption or getattr(titles.get(c.id), "title", c.title),
                    "album": getattr(titles.get(c.id), "title", c.title),
                    "url": f"{host.state['base']}/{c.slug}/",
                }
            )
            if len(out) >= max(1, min(int(n), 24)):
                break
        return out

    host.answer(  # lookup("gallery.photos", {"n": 8, "locale": "en"}): the same, for a module
        "gallery.photos",
        lambda q: photos_of_the_day(
            int((q or {}).get("n", 8)), str((q or {}).get("locale", ""))
        )
        if isinstance(q, dict)
        else photos_of_the_day(),
    )

    @host.context
    def _gallery_photos(request) -> dict:
        locale = str(getattr(request.state, "locale", "") or "")
        return {"gallery_photos": lambda n=8: photos_of_the_day(n, locale)}

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
