"""Content: typed entries, taxonomies, menus and media; the CMS of Nest.

Content types are declared in YAML (any manifest, the application's last);
entries are found by their stored path, so a moved site keeps its addresses;
bodies are sanitized HTML with shortcodes; editors work in the admin panel.
"""

from __future__ import annotations

from nest import ModuleHost
from nest.host import HostError
from nest_content import seo as seo_files
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
    return out


def setup(host: ModuleHost) -> None:
    if host.route != "/":
        raise HostError("content serves whole-site paths; include it with route: /")
    registry = Registry.from_sections(host.sections("content_types"), host.sections("taxonomies"))
    host.state.update(types=registry, settings=host.settings)
    db = host.bound("nest.db")

    listed = [t for t, s in registry.types.items() if not s.hierarchical]

    def latest(n: int, category: str | None) -> list:
        """The newest published entries, for a template (of a category, by its slug)."""
        term = service_mod.term_by(db, "category", slug=category) if category else None
        if category and term is None:
            return []
        entries, _ = service_mod.listing(
            db, types=listed, term_id=term.id if term else None, per_page=max(1, min(int(n), 50))
        )
        return entries

    from nest_content import service as service_mod

    @host.context
    def _content(request):
        from nest_content import service

        return {
            "menu": lambda slug: service.cached_menu(db, slug),
            "content_types": registry.types,
            "absolute_url": lambda path: absolute(request, path),
            "latest": lambda n=3, category=None: latest(n, category),
        }

    from nest_content import service as _service

    def wordpress_post(legacy_id: int) -> dict | None:
        e = _service.entry_by_legacy(db, int(legacy_id))
        if e is None:
            return None
        return {"subject": f"content.entry:{e.id}", "url": e.path, "title": e.title}

    host.answer("wordpress.post", wordpress_post)

    located = [n for n, t in registry.types.items() if "lat" in t.fields and "lng" in t.fields]

    def map_points(_key: object = None) -> list[dict] | None:
        """Each published entry whose type has lat and lng fields, as a place for a map."""
        if not located:
            return None
        from nest_content.seo import summary

        out = []
        for e in _service.published_of_types(db, located):
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
                    "url": e.path,
                    "kind": e.type,
                    "description": summary(e, 120),
                }
            )
        return out

    host.answer("map.points", map_points)
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
    host.admin(admin)
    host.fallback(serve, priority=10)
