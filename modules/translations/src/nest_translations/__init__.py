"""Every module's records in every language of the site.

Modules take part through their manifest (``translatable:``, naming a text table made
with ``nest_db.text_table``) and lookups, so none depends on this one:

* ``{{ translation_fields(subject, id) }}`` in an edit form writes every language's fields
  but the default one (``tr_<language>_<field>``);
* ``nest.lookup("translations.check", {"subject": ..., "id": ..., "form": form})`` tells
  what is wrong with them (or None), before the module saves;
* ``nest.lookup("translations.save", {"subject": ..., "id": ..., "form": form})`` writes
  them, after the module saved the default language's text;
* ``nest.lookup("translations.states", {"subject": ..., "ids": [...]})`` gives
  {id: {language: missing|draft|outdated|published}}, for a module's lists.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from nest import ModuleHost, language_name
from nest_translations import service
from nest_translations.kinds import TranslationsError, discover

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_translations.web import admin

    db = host.bound("nest.db")
    kinds = discover(host.packages(), host.resolve)
    host.state["kinds"] = kinds
    host.state["db"] = db

    def languages() -> tuple[list[str], str]:
        return host.languages, host.default_language

    def kind_of(request_data: dict[str, Any]) -> Any:
        kind = kinds.get(str(request_data.get("subject")))
        if kind is None:
            raise TranslationsError(
                "{subject} is not translated here", subject=request_data.get("subject")
            )
        return kind

    def check(request_data: dict[str, Any]) -> str | None:
        try:
            service.check_form(
                db,
                kind_of(request_data),
                request_data["id"],
                request_data.get("form") or {},
                *languages(),
            )
        except TranslationsError as e:
            return str(e)
        return None

    def save(request_data: dict[str, Any]) -> list[str] | None:
        form = request_data.get("form") or {}
        if not any(str(k).startswith("tr_") for k in form):
            return None  # the form had no translations: nothing to say
        subject = str(request_data.get("subject"))
        changed = service.save_form(
            db, kind_of(request_data), request_data["id"], form, *languages()
        )
        announce(subject, [request_data["id"]], changed)
        return changed

    def states(request_data: dict[str, Any]) -> dict[Any, dict[str, str]]:
        ids = list(request_data.get("ids") or [])
        return service.states(db, kind_of(request_data), *languages(), ids=ids)

    def announce(subject: str, ids: list[Any], locales: list[str]) -> None:
        """Tell the modules a translation changed: an address made from it (a translated
        slug) or a search index follows ("translations.changed")."""
        if ids and locales:
            host.gather(
                "translations.changed", {"subject": subject, "ids": ids, "locales": locales}
            )

    host.state["announce"] = announce
    host.answer("translations.check", check)
    host.answer("translations.save", save)
    host.answer("translations.states", states)
    host.answer("translations.kinds", lambda _key: sorted(kinds))

    @host.context
    def _translations(request: Any) -> dict[str, Any]:
        def fields(
            subject: str, owner_id: Any = None, *, form: Any = None, only: list[str] | None = None
        ) -> Markup:
            kind = kinds.get(subject)
            if kind is None:
                return Markup("")
            site, default = languages()
            wanted = [lang for lang in site if lang != default and (only is None or lang in only)]
            if not wanted:
                return Markup("")
            rows = service.texts(db, kind, owner_id) if owner_id is not None else {}
            source = rows.get(default)
            stand = (
                (service.states(db, kind, site, default, ids=[owner_id]).get(owner_id) or {})
                if owner_id is not None
                else {}
            )
            typed = service.from_form(kind, form, site, default) if form is not None else {}
            values = {}
            for lang in wanted:
                if lang in typed:
                    values[lang] = typed[lang][0] | {"status": typed[lang][1]}
                else:
                    row = rows.get(lang)
                    values[lang] = {f: getattr(row, f) if row else "" for f in kind.fields} | {
                        "status": row.status if row else "published"
                    }
            nest = request.app.state.nest
            context = {
                **nest.template_context(request),
                "kind": kind,
                "languages": wanted,
                "default": default,
                "names": {lang: language_name(lang) for lang in [default, *wanted]},
                "values": values,
                "source": {f: getattr(source, f) for f in kind.fields} if source else None,
                "states": stand,
                "open": only is not None,
            }
            return Markup(nest.templates.get_template("translations/fields.html").render(context))

        return {"translation_fields": fields}

    host.admin(admin)
