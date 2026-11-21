"""Where every record stands in every language, and writing translations: from an edit
form, from the editor, from an import.

A record's source is its text in the default language. A translation records the
source's ``updated_at`` it was made from (``source_updated_at``); when the source changes
later, the translation is outdated until someone saves it again (or says it still holds).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from nest_db import delete_text, save_text, text_rows, text_state
from sqlalchemy import select

from nest_translations.kinds import Kind, TranslationsError

STATES = ("missing", "draft", "outdated", "published")
TODO = ("missing", "draft", "outdated")  # what is left to do
FORMAT = "nest-translations/1"
_SLUG = re.compile(r"[^\s/?#]+")


# --- where things stand ------------------------------------------------------------------------


def _light(db: Any, kind: Kind, ids: list[Any] | None = None) -> dict[Any, dict[str, Any]]:
    """Every record's rows without their text (its state needs only the dates)."""
    m = kind.model
    query = select(m.owner_id, m.locale, m.status, m.updated_at, m.source_updated_at)
    if ids is not None:
        query = query.where(m.owner_id.in_(ids))
    found: dict[Any, dict[str, Any]] = {}
    with db.session() as s:
        for row in s.execute(query):
            found.setdefault(row.owner_id, {})[row.locale] = row
    return found


def states(
    db: Any, kind: Kind, languages: list[str], default: str, ids: list[Any] | None = None
) -> dict[Any, dict[str, str]]:
    """{record: {language: state}} for every language but the default, for the records
    that have a text in the default language (``ids``, or all)."""
    out: dict[Any, dict[str, str]] = {}
    for owner_id, by in _light(db, kind, ids).items():
        source = by.get(default)
        if source is None:
            continue
        out[owner_id] = {
            lang: text_state(by.get(lang), source) for lang in languages if lang != default
        }
    return out


def counts(states_: dict[Any, dict[str, str]], language: str) -> dict[str, int]:
    tally = Counter(by.get(language, "missing") for by in states_.values())
    return {state: tally.get(state, 0) for state in STATES}


def titles(db: Any, kind: Kind, ids: list[Any], default: str) -> dict[Any, str]:
    m = kind.model
    column = getattr(m, kind.title)
    with db.session() as s:
        rows = s.execute(select(m.owner_id, column).where(m.owner_id.in_(ids), m.locale == default))
        return {r[0]: r[1] or f"#{r[0]}" for r in rows}


def texts(db: Any, kind: Kind, owner_id: Any) -> dict[str, Any]:
    """A record's rows, by language."""
    with db.session() as s:
        return text_rows(s, kind.model, [owner_id]).get(owner_id, {})


# --- writing ------------------------------------------------------------------------------------


def _check(db: Any, kind: Kind, owner_id: Any, lang: str, values: dict[str, str]) -> None:
    for field, how in kind.fields.items():
        value = values.get(field, "")
        if how == "slug" and value and not _SLUG.fullmatch(value):
            raise TranslationsError(
                "{language}: the address part '{value}' cannot have spaces, / ? or #",
                language=lang,
                value=value,
            )
    m = kind.model
    with db.session() as s:
        for field in kind.unique:
            value = values.get(field)
            if not value:
                continue
            other = s.scalars(
                select(m.owner_id).where(
                    m.locale == lang, getattr(m, field) == value, m.owner_id != owner_id
                )
            ).first()
            if other is not None:
                raise TranslationsError(
                    "{language}: '{value}' is already another one's {field}",
                    language=lang,
                    value=value,
                    field=field,
                )


def from_form(
    kind: Kind, form: Any, languages: list[str], default: str
) -> dict[str, tuple[dict[str, str], str, bool]]:
    """What a form says for each language it has fields for: (values, status, still
    holds). Its fields are named ``tr_<language>_<field>``."""
    out = {}
    for lang in languages:
        if lang == default or not form.get(f"tr_{lang}_present"):
            continue
        values = kind.cleaned(
            {f: str(form.get(f"tr_{lang}_{f}") or "").strip() for f in kind.fields}
        )
        status = str(form.get(f"tr_{lang}_status") or "published")
        if status not in ("published", "draft"):
            status = "draft"
        out[lang] = (values, status, bool(form.get(f"tr_{lang}_current")))
    return out


def check_form(
    db: Any, kind: Kind, owner_id: Any, form: Any, languages: list[str], default: str
) -> None:
    for lang, (values, _status, _current) in from_form(kind, form, languages, default).items():
        if any(values.values()):
            _check(db, kind, owner_id, lang, values)


def save_form(
    db: Any, kind: Kind, owner_id: Any, form: Any, languages: list[str], default: str
) -> list[str]:
    """Write what a form says for each language (all fields empty: the translation is
    removed); the languages whose text changed. Nothing is written if one is wrong."""
    wanted = from_form(kind, form, languages, default)
    check_form(db, kind, owner_id, form, languages, default)
    changed = []
    with db.session() as s, s.begin():
        source = s.get(kind.model, (owner_id, default))
        if source is None:
            raise TranslationsError("There is no text to translate yet: save the original first.")
        for lang, (values, status, current) in wanted.items():
            if not any(values.values()):
                if delete_text(s, kind.model, owner_id, lang):
                    changed.append(lang)
                continue
            before = s.get(kind.model, (owner_id, lang))
            was = before.status if before is not None else None
            row, did = save_text(s, kind.model, owner_id, lang, values, status=status)
            if did or current or row.source_updated_at is None:
                row.source_updated_at = source.updated_at
            if did or was != status:  # its text, or whether it is shown
                changed.append(lang)
    return changed


# --- export and import --------------------------------------------------------------------------


def export(
    db: Any,
    kinds: list[Kind],
    language: str,
    languages: list[str],
    default: str,
    only: str = "todo",
) -> dict[str, Any]:
    """A language's translations, each beside its source: ``only`` todo (missing, draft,
    outdated), missing, outdated, draft, published or all."""
    if language == default or language not in languages:
        raise TranslationsError(
            "{language} is not one of the site's languages to translate into", language=language
        )
    wanted = TODO if only == "todo" else STATES if only == "all" else (only,)
    items = []
    for kind in kinds:
        stand = states(db, kind, languages, default)
        ids = [i for i, by in stand.items() if by.get(language) in wanted]
        with db.session() as s:
            rows = text_rows(s, kind.model, ids, [default, language])
        for owner_id in ids:
            by = rows.get(owner_id, {})
            source, done = by.get(default), by.get(language)
            if source is None:
                continue
            items.append(
                {
                    "subject": kind.subject,
                    "id": owner_id,
                    "state": stand[owner_id][language],
                    "source": {f: getattr(source, f) for f in kind.fields},
                    "text": {f: getattr(done, f) if done else "" for f in kind.fields},
                    "status": done.status if done else "draft",
                    # to the microsecond: an import compares it with the source's own
                    "source_updated_at": source.updated_at.isoformat()
                    if source.updated_at
                    else None,
                }
            )
    return {"format": FORMAT, "source": default, "locale": language, "items": items}


def import_(
    db: Any, kinds: dict[str, Kind], data: Any, languages: list[str], default: str
) -> tuple[int, list[str], dict[str, list[Any]]]:
    """Write an export's translations back: how many changed, what was refused, and the
    records changed by subject. A translation made from an older source than today's
    comes in outdated, as it is."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise TranslationsError("This is not a Nest translations file.")
    language = str(data.get("locale") or "")
    if language == default or language not in languages:
        raise TranslationsError(
            "{language} is not one of the site's languages to translate into", language=language
        )
    written, refused = 0, []
    touched: dict[str, list[Any]] = {}
    for n, item in enumerate(data.get("items") or [], 1):
        kind = kinds.get(str(item.get("subject")))
        if kind is None:
            refused.append(f"#{n}: {item.get('subject')} is not translated here")
            continue
        text = item.get("text") or {}
        values = kind.cleaned({f: str(text.get(f) or "").strip() for f in kind.fields if f in text})
        if not any(values.values()):
            continue  # left untranslated
        owner_id = item.get("id")
        try:
            _check(db, kind, owner_id, language, values)
        except TranslationsError as e:
            refused.append(f"#{n} ({kind.subject} {owner_id}): {e}")
            continue
        status = item.get("status") if item.get("status") in ("published", "draft") else "draft"
        made_from = item.get("source_updated_at")
        with db.session() as s, s.begin():
            source = s.get(kind.model, (owner_id, default))
            if source is None:
                refused.append(f"#{n} ({kind.subject} {owner_id}): no such record")
                continue
            row, did = save_text(s, kind.model, owner_id, language, values, status=status)
            if did:
                row.source_updated_at = (
                    datetime.fromisoformat(made_from) if made_from else source.updated_at
                )
                written += 1
                touched.setdefault(kind.subject, []).append(owner_id)
    return written, refused, touched
