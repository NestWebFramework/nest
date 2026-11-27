"""Content: typed entries, taxonomies, menus and media; the CMS of Nest.

Content types are declared in YAML (any manifest, the application's last);
entries are found by their stored path, so a moved site keeps its addresses;
bodies are sanitized HTML with shortcodes; editors work in the admin panel.
"""

from __future__ import annotations

from nest import ModuleHost, translator
from nest.host import HostError
from nest_content import seo as seo_files
from nest_content.rich_editor import rich_editor
from nest_content.seo import absolute
from nest_content.service import KIND, EntryData
from nest_content.types import Registry
from nest_content.web import Context, admin, catlist, router, serve, wp_gallery, youtube

__all__ = ["KIND", "Context", "EntryData", "Registry"]


def seo_pages(host: ModuleHost, db: object, registry: Registry) -> list[dict]:
    """Every published entry and every category or tag that holds one, for the sitemap."""
    from nest_content import service as svc
    from nest_content.seo import summary

    admin_root = host.admin_root
    home = host.settings.get("home")
    out: list[dict] = [{"path": "/", "title": host.app_title, "kind": "home", "group": "Home"}]
    for e in svc.published_entries(db):
        out.append(
            {
                "path": e.path,
                "title": e.title,
                "subject": f"content.entry:{e.id}",
                "lastmod": e.updated_at,
                # a deliberate description: the summary editors wrote (not the text's start)
                "description": summary(e) if (e.excerpt or "").strip() else "",
                "images": [{"key": e.featured, "title": e.title}] if e.featured else [],
                "kind": registry.types[e.type].title if e.type in registry.types else e.type,
                "group": registry.types[e.type].title if e.type in registry.types else e.type,
                "text": [e.excerpt or "", e.body or ""],
                "context": [t.name for ts in svc.terms_of(db, e.id).values() for t in ts],
                "edit": f"{admin_root}/content/{e.type}/{e.id}" if admin_root else None,
                "home": e.path == home,
            }
        )
    known = {i["path"] for i in out}
    by_path = {t.path: t for name in registry.taxonomies for t in svc.terms(db, name) if t.path}
    for path, _when in svc.sitemap(db):  # the terms that hold a published entry
        if path in known:
            continue
        known.add(path)
        term = by_path.get(path)
        if term is None:
            out.append({"path": path, "kind": "category", "group": "Categories"})
            continue
        group = "Categories" if term.taxonomy == "category" else "Tags"
        out.append(
            {
                "path": path,
                "title": term.name,
                "subject": f"content.term:{term.id}",  # its search fields, its proposals
                "description": term.description,
                "kind": group,
                "group": group,
                "text": [term.description],
                "edit": f"{admin_root}/content/taxonomies/{term.taxonomy}/{term.id}"
                if admin_root
                else None,
            }
        )
    from nest_content import translated

    for locale in translated.others(registry):  # each translated page at its own address
        entries, terms = translated.published_texts(db, registry, locale)
        tag = locale.upper()
        editor = (
            f"{admin_root}/translations" if admin_root and host.has_module("translations") else None
        )
        for e, row in entries:
            group = registry.types[e.type].title if e.type in registry.types else e.type
            out.append(
                {
                    "path": host.language_url(row.path, locale),
                    "title": row.title or e.title,
                    "subject": f"content.entry:{e.id}",
                    "lastmod": row.updated_at,
                    "description": summary(row) if (row.excerpt or "").strip() else "",
                    "images": [{"key": e.featured, "title": row.title}] if e.featured else [],
                    "kind": group,
                    "group": f"{group} · {tag}",
                    "language": locale,
                    "text": [row.excerpt or "", row.body or ""],
                    "edit": f"{editor}/content.entry/{e.id}?lang={locale}" if editor else None,
                }
            )
        for term, row in terms:
            group = "Categories" if term.taxonomy == "category" else "Tags"
            out.append(
                {
                    "path": host.language_url(row.path, locale),
                    "title": row.name or term.name,
                    "subject": f"content.term:{term.id}",
                    "description": row.description,
                    "kind": group,
                    "group": f"{group} · {tag}",
                    "language": locale,
                    "text": [row.description],
                    "edit": f"{editor}/content.term/{term.id}?lang={locale}" if editor else None,
                }
            )
    return out


def _kind(value: object) -> str:
    kind = str(value or "").strip()
    return kind if kind in ("stars", "helpful", "updown") else ""


def setup(host: ModuleHost) -> None:
    if host.route != "/":
        raise HostError("content serves whole-site paths; include it with route: /")
    registry = Registry.from_sections(host.sections("content_types"), host.sections("taxonomies"))
    registry.default_language, registry.languages = host.default_language, host.languages
    host.state.update(types=registry, settings=host.settings, language_url=host.language_url)
    db = host.bound("nest.db")
    # records made before their text tables (or by an older version): their default
    # language's text rows, once (one statement per table, nothing when none is missing)
    from sqlalchemy.exc import SQLAlchemyError

    from nest_content import translated

    try:
        made = translated.backfill(db, registry.default_language)
    except SQLAlchemyError as e:  # not migrated yet (NEST_MIGRATE=off, a db command)
        made = 0
        host.log.warning(
            "content: the text tables are not ready (%s); migrate the database",
            e.__class__.__name__,
        )
    if made:
        host.log.info(
            "content: %d texts in %s written to the text tables", made, registry.default_language
        )

    def on_translated(change: dict) -> None:
        """A translation was written (translations module): its addresses and its search
        index follow, and the menus are made again."""
        subject, ids, locales = (
            change.get("subject"),
            list(change.get("ids") or []),
            list(change.get("locales") or []),
        )
        search = host.bound("nest.search")
        if subject == "content.entry":
            with db.session() as s, s.begin():
                documents = translated.refresh_entries(s, registry, ids, locales)
            translated.apply(search, documents)
        elif subject == "content.term":
            with db.session() as s, s.begin():
                documents = translated.refresh_terms(s, registry, ids, locales)
            translated.apply(search, documents)
        elif subject != "content.menu_item":
            return
        service_mod.changed()

    host.answer("translations.changed", on_translated)

    listed = [t for t, s in registry.types.items() if not s.hierarchical]

    def latest(n: int, category: str | None, locale: str = "", taxonomy: str = "category") -> list:
        """The newest published entries, for a template (of a category, or of another
        taxonomy's term, by its slug)."""
        term = service_mod.term_by(db, taxonomy, slug=category) if category else None
        if category and term is None:
            return []
        entries, _ = service_mod.listing(
            db, types=listed, term_id=term.id if term else None, per_page=max(1, min(int(n), 50))
        )
        return translated.show_entries(db, registry, entries, locale)

    from nest_content import service as service_mod

    def category(slug: str, taxonomy: str, locale: str) -> object:
        """A category (a tag) by its default slug, as the page's language shows it (its
        name, its address), or None: a theme's section titled by the category's own name."""
        term = service_mod.term_by(db, taxonomy, slug=slug) if slug else None
        return translated.show_terms(db, registry, [term], locale)[0] if term else None

    def categories(taxonomy: str, locale: str) -> list:
        """A taxonomy's terms that hold a published entry, each with how many, in the page's
        language: a sidebar's list ({% for t, n in categories() %})."""
        if taxonomy not in registry.taxonomies:
            return []
        found = [(t, n) for t, _depth, n in service_mod.term_tree(db, taxonomy) if n]
        shown = translated.show_terms(db, registry, [t for t, _n in found], locale)
        return list(zip(shown, [n for _t, n in found], strict=True))

    def related(entry: object, n: int, locale: str) -> list:
        """Other published entries of an entry's first category, newest first, in the page's
        language: what to read next under an article."""
        own = getattr(entry, "id", None)
        if own is None:
            return []
        first = (service_mod.terms_of(db, own).get("category") or [None])[0]
        if first is None:
            return []
        entries, _ = service_mod.listing(db, types=listed, term_id=first.id, per_page=int(n) + 1)
        others = [e for e in entries if e.id != own][: int(n)]
        return translated.show_entries(db, registry, others, locale)

    def term_url(slug: str, taxonomy: str, locale: str) -> str:
        """A category's (a tag's) address in the page's language, by its default slug: what a
        template links to ({{ term_url("stiai-ca") }}), so its English page links in English."""
        term = service_mod.term_by(db, taxonomy, slug=slug)
        if term is None:
            return f"/category/{slug}/"
        return translated.show_terms(db, registry, [term], locale)[0].path or term.path

    @host.context
    def _content(request):
        from nest_content import service
        from nest_content.web import locale_of

        locale = locale_of(request)
        return {
            "menu": lambda slug: service.cached_menu(db, slug, locale, registry),
            "content_types": registry.types,
            "absolute_url": lambda path: absolute(request, path),
            "latest": lambda n=3, category=None, taxonomy="category": latest(
                n, category, locale, taxonomy
            ),
            "term_url": lambda slug, taxonomy="category": term_url(slug, taxonomy, locale),
            "categories": lambda taxonomy="category": categories(taxonomy, locale),
            "category": lambda slug, taxonomy="category": category(slug, taxonomy, locale),
            "related": lambda entry, n=3: related(entry, n, locale),
            # how visitors judge an entry (the rating module): stars, helpful, updown, or none
            "content_rating": _kind(host.settings.get("rating")),
            # the rich text editor for any admin form (see nest_content.rich_editor)
            "rich_editor": lambda: rich_editor(
                translator(request), request.app.state.nest.asset, request.app.state.nest.admin_root
            ),
        }

    from nest_content import service as _service

    def wordpress_post(legacy_id: int) -> dict | None:
        e = _service.entry_by_legacy(db, int(legacy_id))
        if e is None:
            return None
        return {"subject": f"content.entry:{e.id}", "url": e.path, "title": e.title}

    host.answer("wordpress.post", wordpress_post)

    def site_menus(_key: object = None) -> list[dict[str, str]]:
        """The site's menus, for another module's "link it from a menu" (the admin panel)."""
        from sqlalchemy import select  # noqa: PLC0415

        from nest_content.models import Menu  # noqa: PLC0415

        with db.session() as s:
            return [
                {"slug": m.slug, "title": m.title}
                for m in s.scalars(select(Menu).order_by(Menu.title))
            ]

    def menu_link(key: dict) -> dict | None:
        """A link added at the end of a menu: {"menu": slug, "title", "url"}."""
        import re  # noqa: PLC0415

        from sqlalchemy import func, select  # noqa: PLC0415

        from nest_content import translated  # noqa: PLC0415
        from nest_content.models import Menu, MenuItem  # noqa: PLC0415

        url, title = str(key.get("url", "")).strip()[:1000], str(key.get("title", "")).strip()[:200]
        if not title or not re.match(r"^(/|https?://)", url):
            return None
        with db.session() as s:
            m = s.scalar(select(Menu).where(Menu.slug == str(key.get("menu", ""))))
            last = (
                s.scalar(select(func.max(MenuItem.position)).where(MenuItem.menu_id == m.id))
                if m
                else 0
            )
        if m is None:
            return None
        item = service_mod.add_menu_item(db, m.id, title=title, url=url, position=(last or 0) + 1)
        with db.session() as s, s.begin():
            translated.mirror_menu_item(s, registry, s.get(MenuItem, item.id))
        return {"id": item.id, "menu": m.slug}

    host.answer("content.menus", site_menus)
    host.answer("content.menu.link", menu_link)

    located = [n for n, t in registry.types.items() if "lat" in t.fields and "lng" in t.fields]

    def map_points(key: object = None) -> list[dict] | None:
        """Each published entry whose type has lat and lng fields, as a place for a map
        (in the map's language, ``{"locale": "en"}``: its words and address there)."""
        if not located:
            return None
        from nest_content.seo import summary

        locale = str(key.get("locale") or "") if isinstance(key, dict) else ""
        entries = translated.show_entries(
            db, registry, _service.published_of_types(db, located), locale
        )
        out = []
        for e in entries:
            f = e.fields or {}
            try:
                lat, lng = float(f["lat"]), float(f["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "title": e.title,
                    "url": host.language_url(e.path, locale) if locale else e.path,
                    "kind": e.type,
                    "description": summary(e, 120),
                }
            )
        return out

    host.answer("map.points", map_points)

    def entries_of(key: object = None) -> list[dict] | None:
        """``host.lookup("content.entries", {"type": "efemeride"})``: a type's published
        entries (id, title, path, fields, excerpt, a line about each, the featured picture's
        key, when published), for a module that shows them its way (the almanac's
        on-this-day, a settlement's page). ``"body": True`` gives each one's body too (its
        stored, cleaned HTML)."""
        kind = str(key.get("type") or "") if isinstance(key, dict) else ""
        if not kind or kind not in registry.types:
            return None
        from nest_content.seo import summary

        with_body = bool(key.get("body")) if isinstance(key, dict) else False
        return [
            {
                "id": e.id,
                "title": e.title,
                "path": e.path,
                "fields": dict(e.fields or {}),
                "summary": summary(e, 160),
                "excerpt": e.excerpt,
                "featured": e.featured,
                "published_at": e.published_at,
                **({"body": e.body} if with_body else {}),
            }
            for e in _service.published_of_types(db, [kind])
        ]

    host.answer("content.entries", entries_of)
    from nest_content.seo import summary

    host.template_filter("summary", summary)  # {{ entry | summary(130) }}: a line about it
    host.shortcode("catlist", catlist)
    host.shortcode("youtube", youtube)
    if not host.has_module("gallery"):
        # WordPress's own [gallery ids="..."]; the gallery module answers [gallery] when present.
        host.shortcode("gallery", wp_gallery)
    host.mount(seo_files.router)  # the feed
    if not host.has_module("seo"):  # the seo module serves these, with every module's pages
        host.mount(seo_files.files)
    host.answer("seo.urls", lambda _key=None: seo_pages(host, db, registry))

    def seo_text(subject: object) -> dict | None:
        """A category's (or a tag's) words for a proposal: what its entries are called and
        say, and a first line naming them, for a page that has little text of its own."""
        kind, _, ident = str(subject).partition(":")
        if kind != "content.term" or not ident.isdigit():
            return None
        from nest_content import service as svc

        term = svc.term_by_id(db, int(ident))
        if term is None:
            return None
        entries, _total = svc.listing(db, term_id=term.id, per_page=30)
        titles = [e.title for e in entries]
        shown = ", ".join(titles[:6]) + ("…" if len(titles) > 6 else "")
        lead = [f"{term.name}: {shown}."] if titles else []  # after its own description
        return {
            "lead": lead,
            "text": [f"{e.title}. {e.excerpt or ''}" for e in entries]
            + [e.body for e in entries[:10]],
            "context": [],
        }

    host.answer("seo.text", seo_text)
    host.mount(router)
    from nest_content.menus_admin import menus as _menus

    # the menus' pages first, so /menus is never taken for a content type's
    admin.routes[:0] = [r for r in _menus.routes if r not in admin.routes]
    host.admin(admin)
    host.fallback(serve, priority=10)
