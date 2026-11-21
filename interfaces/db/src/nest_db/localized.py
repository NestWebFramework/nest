"""A record's text in every language: a companion table, one row per record per language.

A module keeps what is the same in every language in its own table (an article's type,
author, date, pictures) and its text beside it, one row per language, the default one
included::

    class Entry(Base):
        __tablename__ = "content_entry"
        id: Mapped[int] = mapped_column(primary_key=True)
        ...

    EntryText = text_table(Base, Entry, title=String(300), slug=String(200),
                           body=Text, unique=("slug",))

makes ``content_entry_text``: ``owner_id`` and ``locale`` (together its key), the given
columns, a per-language ``status`` (``published`` or ``draft``), ``updated_at`` (when
its text last changed) and ``source_updated_at`` (the default language's ``updated_at``
the translation was made from: a later change there makes it outdated). ``unique``
fields are unique per language (two languages may share a slug, one language may not).

Adding a language adds rows, never columns. Reading is one indexed query, whatever the
number of languages: :func:`localize` for a listing, :func:`by_slug` for an address.
A module reads and writes its own rows with these; the ``translations`` module, when the
application has it, adds the editors' side (every language's fields, what is missing
or outdated, export and import).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, delete, select
from sqlalchemy.orm import MappedColumn, Session, mapped_column
from sqlalchemy.types import TypeEngine

__all__ = [
    "Localized",
    "by_slug",
    "delete_text",
    "localize",
    "save_text",
    "text_rows",
    "text_state",
    "text_table",
]

RESERVED = frozenset({"owner_id", "locale", "status", "updated_at", "source_updated_at"})
STATES = ("published", "draft")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def text_table(
    base: Any,
    owner: type,
    *,
    unique: Iterable[str] = (),
    index: Iterable[str] = (),
    **fields: Any,
) -> type:
    """The companion text table of ``owner`` (a mapped class with one primary key column),
    in ``base``'s module; each field a type (``String(300)``, ``Text``) or a
    ``mapped_column(...)``. ``unique`` fields are unique within a language; ``index``
    fields are looked up within one (an index on the locale and the field)."""
    if not fields:
        raise TypeError(f"{owner.__name__}: a text table needs at least one field")
    taken = RESERVED & set(fields)
    if taken:
        raise TypeError(f"{owner.__name__}: {', '.join(sorted(taken))} is the text table's own")
    keys = list(owner.__table__.primary_key.columns)
    if len(keys) != 1:
        raise TypeError(f"{owner.__name__}: a text table needs an owner with one key column")
    key = keys[0]
    unique, index = tuple(unique), tuple(index)
    for name in (*unique, *index):
        if name not in fields:
            raise TypeError(f"{owner.__name__}: '{name}' is not one of its fields")
    table = f"{owner.__tablename__}_text"
    attrs: dict[str, Any] = {
        "__tablename__": table,
        "__table_args__": (
            *(UniqueConstraint("locale", n, name=f"uq_{table}_locale_{n}") for n in unique),
            *(Index(f"ix_{table}_locale_{n}", "locale", n) for n in index),
        ),
        "__module__": owner.__module__,
        "owner_id": mapped_column(
            key.type,
            ForeignKey(f"{owner.__tablename__}.{key.name}", ondelete="CASCADE"),
            primary_key=True,
        ),
        "locale": mapped_column(String(16), primary_key=True, index=True),
        "status": mapped_column(String(16), default="published", nullable=False),
        "updated_at": mapped_column(DateTime, default=_now, nullable=False),
        "source_updated_at": mapped_column(DateTime, nullable=True),
    }
    for name, spec in fields.items():
        if isinstance(spec, MappedColumn):
            attrs[name] = spec
        elif isinstance(spec, TypeEngine) or (
            isinstance(spec, type) and issubclass(spec, TypeEngine)
        ):
            attrs[name] = mapped_column(spec, default="", nullable=False)
        else:
            raise TypeError(f"{owner.__name__}.{name}: a column type or mapped_column(...)")
    name = f"{owner.__name__}Text"
    attrs["__qualname__"] = name
    attrs["__text_fields__"] = tuple(fields)
    attrs["__text_unique__"] = unique
    attrs["__text_owner__"] = owner
    cls = type(name, (base,), attrs)
    owner.__text_model__ = cls
    return cls


def text_rows(
    session: Session, model: type, ids: Iterable[Any], locales: Iterable[str] | None = None
) -> dict[Any, dict[str, Any]]:
    """Every text of ``ids`` (in ``locales``, or all), as {owner id: {locale: row}}."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    query = select(model).where(model.owner_id.in_(ids))
    if locales is not None:
        query = query.where(model.locale.in_(list(locales)))
    found: dict[Any, dict[str, Any]] = {}
    for row in session.scalars(query):
        found.setdefault(row.owner_id, {})[row.locale] = row
    return found


@dataclass(frozen=True)
class Localized:
    """The text a page shows of one record: its row, and whether it is the default
    language's standing in for a missing translation (``fallback``)."""

    text: Any
    fallback: bool

    @property
    def locale(self) -> str:
        return self.text.locale

    def __getattr__(self, name: str) -> Any:
        return getattr(self.text, name)


def _shown(row: Any, drafts: bool) -> bool:
    return row is not None and (drafts or row.status == "published")


def localize(
    session: Session,
    model: type,
    ids: Iterable[Any],
    locale: str,
    default: str,
    *,
    fallback: bool = True,
    drafts: bool = False,
) -> dict[Any, Localized]:
    """The text of each of ``ids`` in ``locale``, one query: where there is none (or it
    is a draft and ``drafts`` is false), the default language's when ``fallback``, else
    the record is left out."""
    rows = text_rows(session, model, ids, {locale, default})
    out: dict[Any, Localized] = {}
    for owner_id, by in rows.items():
        wanted = by.get(locale)
        if _shown(wanted, drafts):
            out[owner_id] = Localized(wanted, False)
        elif fallback and locale != default and _shown(by.get(default), drafts):
            out[owner_id] = Localized(by[default], True)
    return out


def by_slug(
    session: Session,
    model: type,
    locale: str,
    value: str,
    *,
    field: str = "slug",
    drafts: bool = False,
) -> Any:
    """The text row whose ``field`` is ``value`` in ``locale`` (an address), or None."""
    query = select(model).where(model.locale == locale, getattr(model, field) == value)
    if not drafts:
        query = query.where(model.status == "published")
    return session.scalars(query.limit(1)).first()


_KEEP: Any = object()


def save_text(
    session: Session,
    model: type,
    owner_id: Any,
    locale: str,
    values: Mapping[str, Any],
    *,
    status: str | None = None,
    source_updated_at: datetime | None = _KEEP,
) -> tuple[Any, bool]:
    """Write ``owner_id``'s text in ``locale`` (only the given fields): the row, and
    whether its text changed. ``updated_at`` moves only when it did, so a translation
    made from it is outdated only by a real change."""
    unknown = set(values) - set(model.__text_fields__)
    if unknown:
        raise ValueError(f"{model.__name__}: no field {', '.join(sorted(unknown))}")
    if status is not None and status not in STATES:
        raise ValueError(f"'{status}' is not a text's state ({', '.join(STATES)})")
    row = session.get(model, (owner_id, locale))
    changed = row is None
    if row is None:
        row = model(owner_id=owner_id, locale=locale, status=status or "published")
        columns = model.__table__.columns
        for name in model.__text_fields__:  # empty; a nullable one (a derived address) NULL
            setattr(row, name, None if columns[name].nullable else "")
        session.add(row)
    for name, value in values.items():
        value = "" if value is None else value
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    if status is not None:
        row.status = status
    if source_updated_at is not _KEEP:
        row.source_updated_at = source_updated_at
    if changed:
        row.updated_at = _now()
    return row, changed


def delete_text(session: Session, model: type, owner_id: Any, locale: str) -> bool:
    """Forget ``owner_id``'s text in ``locale``; whether there was one."""
    done = session.execute(delete(model).where(model.owner_id == owner_id, model.locale == locale))
    return bool(done.rowcount)


def text_state(row: Any, source: Any) -> str:
    """Where a translation stands: ``missing``, ``draft``, ``outdated`` (the default
    language's text changed after it was made) or ``published``."""
    if row is None:
        return "missing"
    if row.status == "draft":
        return "draft"
    if (
        source is not None
        and source is not row
        and source.updated_at is not None
        and (row.source_updated_at is None or source.updated_at > row.source_updated_at)
    ):
        return "outdated"
    return "published"


class Overlaid:
    """A record as a page in one language shows it: its text there laid over it (the
    record's other attributes as they are), or the record itself where there is no
    published text in that language (``fallback``: the default language's standing in).
    ``language`` is the language of the text shown."""

    __slots__ = ("_record", "_text", "fallback", "language")

    def __init__(self, record: Any, text: Mapping[str, Any], language: str, fallback: bool):
        self._record, self._text = record, dict(text)
        self.language, self.fallback = language, fallback

    def __getattr__(self, name: str) -> Any:
        text = object.__getattribute__(self, "_text")
        if name in text:
            return text[name]
        return getattr(object.__getattribute__(self, "_record"), name)

    def __repr__(self) -> str:
        record = object.__getattribute__(self, "_record")
        return f"<Overlaid {record!r} in {self.language}{' (fallback)' if self.fallback else ''}>"


def overlay(
    session: Session,
    model: type,
    records: Iterable[Any],
    locale: str,
    default: str,
    *,
    key: str = "id",
    keep_empty: Iterable[str] = (),
) -> list[Any]:
    """``records`` as a page in ``locale`` shows them, one query: each with its published
    text there laid over it, else as it is (``fallback``). In the default language the
    records are given back as they are. An empty translated field leaves the record's
    own, but for ``keep_empty`` fields (a translation may mean to say nothing there)."""
    records = list(records)
    if not records or not locale or locale == default:
        return records
    ids = [getattr(r, key) for r in records]
    rows = {
        row.owner_id: row
        for row in session.scalars(
            select(model).where(
                model.owner_id.in_(ids), model.locale == locale, model.status == "published"
            )
        )
    }
    keep = set(keep_empty)
    out: list[Any] = []
    for r in records:
        row = rows.get(getattr(r, key))
        if row is None:
            out.append(Overlaid(r, {}, default, True))
            continue
        text = {f: getattr(row, f) for f in model.__text_fields__ if getattr(row, f) or f in keep}
        out.append(Overlaid(r, text, locale, False))
    return out
