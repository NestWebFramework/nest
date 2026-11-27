"""SEO for every module of an application: what search engines and shared links are told.

Modules take part through lookups, so none depends on this one:

* ``nest.lookup("seo.save", {"subject": "content.entry:12", "form": form})`` keeps the
  seo_* fields of an edit form (``{{ seo_fields(subject) }}`` writes them);
* ``nest.lookup("seo.forget", subject)`` when the record is gone;
* a module answers ``"seo.urls"`` with its public pages for the sitemap;
* a page's head is ``{{ seo_head(subject, title=..., description=..., image=...) }}``
  and its title ``{{ seo_page_title(subject, title) }}``.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from nest import ModuleHost
from nest_seo import service
from nest_seo.analytics import analytics
from nest_seo.head import head, title
from nest_seo.service import SeoError

__all__ = ["SUBJECT_FIELDS"]

SUBJECT_FIELDS = (
    "seo_title",
    "seo_description",
    "seo_keywords",
    "seo_image",
    "seo_canonical",
    "seo_noindex",
)


class Hidden:
    """While the "hidden" setting is on, every answer says X-Robots-Tag: noindex, nofollow
    (pages without a robots meta tag, pictures and files too)."""

    def __init__(self, app: Any, settings: Any) -> None:
        self.app, self.settings = app, settings

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self.settings.get("hidden"):
            await self.app(scope, receive, send)
            return

        async def tagged(message: Any) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-robots-tag", b"noindex, nofollow"),
                ]
            await send(message)

        await self.app(scope, receive, tagged)


def setup(host: ModuleHost) -> None:
    from nest_seo.web import admin, root

    host.state["settings"] = host.settings
    host.add_middleware(Hidden, settings=host.settings)
    db_ = host.bound("nest.db")
    service.set_default(db_, host.default_language)
    from sqlalchemy.exc import SQLAlchemyError

    try:  # what was said before the text table: its default language's rows, once
        service.backfill(db_, host.default_language)
    except SQLAlchemyError as e:
        host.log.warning(
            "seo: the text table is not ready (%s); migrate the database", e.__class__.__name__
        )
    host.answer("seo.site_url", lambda _key: str(host.settings.get("site_url") or "") or None)
    db = host.bound("nest.db")

    def save(request_data: dict[str, Any]) -> bool | None:
        form = request_data.get("form") or {}
        if not form.get("seo_present"):
            return None  # the form had no seo fields: nothing to say
        values = service.clean({k[4:]: form.get(k, "") for k in SUBJECT_FIELDS})
        service.save(db, str(request_data["subject"]), values)
        return True

    def check(request_data: dict[str, Any]) -> str | None:
        """The problem with a form's seo fields, or None (asked before the module saves)."""
        form = request_data.get("form") or {}
        if not form.get("seo_present"):
            return None
        try:
            service.clean({k[4:]: form.get(k, "") for k in SUBJECT_FIELDS})
        except SeoError as e:
            return e.message
        return None

    host.answer("seo.save", save)
    host.answer("seo.check", check)
    host.answer("seo.forget", lambda subject: service.forget(db, str(subject)) or True)
    host.answer("seo.meta", lambda subject: service.get(db, str(subject)))
    # a module uninstalled from the application: what was said about its pages goes too
    host.answer("module.removed", lambda name: service.forget_module(db, str(name)))

    @host.context
    def _seo(request: Any) -> dict[str, Any]:
        def fields(
            subject: str,
            *,
            path: str = "",
            default_title: str = "",
            default_description: str = "",
            form: Any = None,
            picker: dict[str, str] | None = None,
        ) -> Markup:
            meta = service.get(db, subject) if subject else None
            if form is not None and form.get("seo_present"):  # the form came back: what was typed
                values = {k[4:]: form.get(k, "") for k in SUBJECT_FIELDS}
            else:
                values = {n: getattr(meta, n) if meta else "" for n in service.FIELDS}
            from nest_seo.head import site_url

            nest = request.app.state.nest
            context = {
                **nest.template_context(request),
                "values": values,
                "subject": subject,
                "path": path,
                "default_title": default_title,
                "default_description": default_description
                or str(host.settings.get("description") or ""),
                "site": nest.title,
                "base_url": site_url(request),
                "picker": picker,
            }
            return Markup(nest.templates.get_template("seo/fields.html").render(context))

        return {
            "seo_head": lambda subject="", **kw: head(request, subject, **kw),
            "seo_page_title": lambda subject, default: title(request, subject, default),
            "seo_fields": fields,
            "seo_meta": lambda subject: service.get(db, subject) if subject else None,
            # Google Analytics, when its ID is set (the layouts include seo/analytics.html)
            "seo_analytics": lambda: analytics(host),
        }

    def cookies(_key: object = None) -> list[dict]:
        """Google Analytics' cookies, for the consent module, while an ID is set."""
        from nest_seo.analytics import measurement_id

        found = measurement_id(host.settings.get("google_analytics"))
        if not found:
            return []
        common = {
            "purpose": "statistics",
            "service": "google-analytics",
            "provider": "Google Analytics",
            "owner": "seo",
            "description": "Helps us see which pages are useful, so we can make the site better.",
        }
        return [
            {**common, "name": "_ga", "duration": "2 years"},
            {**common, "name": f"_ga_{found[2:]}", "duration": "2 years"},
        ]

    host.answer("consent.cookies", cookies)
    host.serve_at_root(root)
    host.admin(admin)
