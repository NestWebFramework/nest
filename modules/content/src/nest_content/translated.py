"""Content in every language of the site.

An entry's (a term's, a menu item's) text is in its text table, one row per language
(``models.EntryText``...). The default language's row mirrors the record's own columns,
which its pages read without a join; it is written with them (``mirror_*``), and made at
start for records older than the text tables (``backfill``). The other languages' rows
are written by editors through the translations module; their addresses are made here,
from the translated slugs of the entry, its category and its parents, a link without
a translation taking the default slug (``refresh_entries``, ``refresh_terms``).

A page in another language shows the record through :class:`Shown`: the translated
text over the record, or the default language's standing in (``fallback``) where there
is no published translation, so templates read ``entry.title`` and ``entry.path`` as
ever. Each language's text is in the search index under its own kind
(``content.entry.en``).
"""

from __future__ import annotations

from typing import Any

from nest_db import save_text
from nest_search import Document
from sqlalchemy import exists, insert, literal, null, or_, select

from nest.text import slugify
from nest_content.models import (
    Entry,
    EntryTerm,
    EntryText,
    MenuItem,
    MenuItemText,
    Term,
    TermText,
    utcnow,
)
from nest_content.types import Registry, build_path, term_path

KIND = "content.entry"
ENTRY_TEXT = ("title", "slug", "excerpt", "body")
TERM_TEXT = ("name", "slug", "description")


def others(registry: Registry) -> list[str]:
    """The site's languages but the default one."""
    return [x for x in registry.languages if x != registry.default_language]


def kind_for(locale: str, registry: Registry) -> str:
    """The search index's kind for a language's entries (the default's is KIND)."""
    return KIND if not locale or locale == registry.default_language else f"{KIND}.{locale}"


# --- the default language's text, mirrored --------------------------------------------------


def mirror_entry(s: Any, registry: Registry, e: Entry) -> None:
    if not registry.default_language or e.id is None or e.language:
        return  # (an entry with a language of its own, an old way, has its own addresses)
    values = {f: getattr(e, f) or "" for f in ENTRY_TEXT}
    row, _ = save_text(s, EntryText, e.id, registry.default_language, values, status="published")
    row.path = e.path  # derived: a moved address is not a changed text (nothing is outdated)


def mirror_term(s: Any, registry: Registry, t: Term) -> None:
    if not registry.default_language or t.id is None:
        return
    values = {f: getattr(t, f) or "" for f in TERM_TEXT}
    row, _ = save_text(s, TermText, t.id, registry.default_language, values, status="published")
    row.path = t.path or None


def mirror_menu_item(s: Any, registry: Registry, item: MenuItem) -> None:
    """Only a label of its own, or a link of its own, has anything to translate."""
    if not registry.default_language or item.id is None:
        return
    if item.title or not (item.entry_id or item.term_id):
        values = {"title": item.title or "", "url": item.url or ""}
        save_text(s, MenuItemText, item.id, registry.default_language, values, status="published")


def backfill(db: Any, default: str) -> int:
    """The default language's rows of the records that have none (made before the text
    tables, or by an older version): one statement per table; how many were made."""
    if not default:
        return 0
    made = 0
    now = utcnow()
    with db.session() as s, s.begin():
        has = exists().where(EntryText.owner_id == Entry.id, EntryText.locale == default)
        made += (
            s.execute(
                insert(EntryText).from_select(
                    [
                        "owner_id",
                        "locale",
                        "status",
                        "updated_at",
                        "source_updated_at",
                        "path",
                        *ENTRY_TEXT,
                    ],
                    select(
                        Entry.id,
                        literal(default),
                        literal("published"),
                        Entry.updated_at,
                        null(),
                        Entry.path,
                        *(getattr(Entry, f) for f in ENTRY_TEXT),
                    ).where(~has, Entry.language == ""),
                )
            ).rowcount
            or 0
        )
        has = exists().where(TermText.owner_id == Term.id, TermText.locale == default)
        made += (
            s.execute(
                insert(TermText).from_select(
                    [
                        "owner_id",
                        "locale",
                        "status",
                        "updated_at",
                        "source_updated_at",
                        "path",
                        *TERM_TEXT,
                    ],
                    select(
                        Term.id,
                        literal(default),
                        literal("published"),
                        literal(now),
                        null(),
                        Term.path,
                        *(getattr(Term, f) for f in TERM_TEXT),
                    ).where(~has),
                )
            ).rowcount
            or 0
        )
        has = exists().where(MenuItemText.owner_id == MenuItem.id, MenuItemText.locale == default)
        own = or_(MenuItem.title != "", MenuItem.entry_id.is_(None) & MenuItem.term_id.is_(None))
        made += (
            s.execute(
                insert(MenuItemText).from_select(
                    [
                        "owner_id",
                        "locale",
                        "status",
                        "updated_at",
                        "source_updated_at",
                        "title",
                        "url",
                    ],
                    select(
                        MenuItem.id,
                        literal(default),
                        literal("published"),
                        literal(now),
                        null(),
                        MenuItem.title,
                        MenuItem.url,
                    ).where(~has, own),
                )
            ).rowcount
            or 0
        )
    return made


# --- what a page shows -------------------------------------------------------------------------


class Shown:
    """A record as a page in one language shows it: the translated text over the record
    (its id, type, fields, pictures and dates are the record's), or, where there is no
    published translation, the default language's (``fallback``). ``language`` is the
    language of the text shown."""

    __slots__ = ("_record", "_text", "fallback", "language")

    def __init__(self, record: Any, text: dict[str, Any], language: str, fallback: bool):
        self._record, self._text = record, text
        self.language, self.fallback = language, fallback

    def __getattr__(self, name: str) -> Any:
        text = object.__getattribute__(self, "_text")
        if name in text:
            return text[name]
        return getattr(object.__getattribute__(self, "_record"), name)

    def __repr__(self) -> str:
        return (
            f"<Shown {self._record!r} in {self.language}{' (fallback)' if self.fallback else ''}>"
        )


def _overlay(row: Any, fields: tuple[str, ...], named: str) -> dict[str, Any]:
    text = {f: getattr(row, f) for f in fields}
    if not text.get(named):  # a translation without its title keeps the original's
        text.pop(named)
    if not text.get("slug"):
        text.pop("slug", None)
    if row.path:
        text["path"] = row.path
    return text


def _published(s: Any, model: Any, ids: list[Any], locale: str) -> dict[Any, Any]:
    if not ids:
        return {}
    rows = s.scalars(
        select(model).where(
            model.owner_id.in_(ids), model.locale == locale, model.status == "published"
        )
    )
    return {r.owner_id: r for r in rows}


def wanted(registry: Registry, locale: str | None) -> bool:
    """Whether a page in ``locale`` shows anything but the records' own text."""
    return bool(locale) and locale != registry.default_language and locale in registry.languages


def show_entries(db: Any, registry: Registry, entries: list[Any], locale: str | None) -> list[Any]:
    """The entries as a page in ``locale`` shows them (as they are, in the default)."""
    if not entries or not wanted(registry, locale):
        return entries
    with db.session() as s:
        rows = _published(s, EntryText, [e.id for e in entries], locale)
    out = []
    for e in entries:
        row = rows.get(e.id)
        if row is None:
            out.append(Shown(e, {}, registry.default_language, True))
        else:
            out.append(Shown(e, _overlay(row, ENTRY_TEXT, "title"), locale, False))
    return out


def show_terms(db: Any, registry: Registry, terms: list[Any], locale: str | None) -> list[Any]:
    if not terms or not wanted(registry, locale):
        return terms
    with db.session() as s:
        rows = _published(s, TermText, [t.id for t in terms], locale)
    return [
        Shown(t, _overlay(rows[t.id], TERM_TEXT, "name"), locale, False)
        if t.id in rows
        else Shown(t, {}, registry.default_language, True)
        for t in terms
    ]


def show_term_groups(
    db: Any, registry: Registry, groups: dict[str, list[Any]], locale: str | None
) -> dict[str, list[Any]]:
    if not wanted(registry, locale):
        return groups
    flat = show_terms(db, registry, [t for ts in groups.values() for t in ts], locale)
    by_id = {t.id: t for t in flat}
    return {name: [by_id[t.id] for t in ts] for name, ts in groups.items()}


# --- found by its address, in any language -------------------------------------------------


def entry_at(db: Any, registry: Registry, path: str, locale: str | None) -> tuple[Any, str | None]:
    """The published entry at ``path`` for a page in ``locale``, or where to send the
    visitor instead (``(None, path)``: the address of another language's text, or the
    default one's when this language has its own): ``(None, None)`` when there is none."""
    default = registry.default_language
    with db.session() as s:
        live = (Entry.status == "published") & (Entry.language == "")
        if wanted(registry, locale):
            row = s.scalar(
                select(EntryText)
                .join(Entry, Entry.id == EntryText.owner_id)
                .where(
                    EntryText.locale == locale,
                    EntryText.path == path,
                    EntryText.status == "published",
                    live,
                )
            )
            if row is not None:
                return s.get(Entry, row.owner_id), None
        e = s.scalar(select(Entry).where(Entry.path == path, live))
        if e is not None:
            if wanted(registry, locale):
                own = _published(s, EntryText, [e.id], locale).get(e.id)
                if own is not None and own.path and own.path != path:
                    return None, own.path  # this language has its own address
            return e, None
        # another language's address (a switch of language, a shared link)
        row = s.scalar(
            select(EntryText)
            .join(Entry, Entry.id == EntryText.owner_id)
            .where(EntryText.path == path, EntryText.locale != default, live)
            .limit(1)
        )
        if row is None:
            return None, None
        e = s.get(Entry, row.owner_id)
        if wanted(registry, locale):
            own = _published(s, EntryText, [e.id], locale).get(e.id)
            if own is not None and own.path:
                return None, own.path
        return None, e.path


def term_at(db: Any, registry: Registry, path: str, locale: str | None) -> tuple[Any, str | None]:
    """As :func:`entry_at`, for a category's (a tag's) page."""
    default = registry.default_language
    with db.session() as s:
        if wanted(registry, locale):
            row = s.scalar(
                select(TermText).where(
                    TermText.locale == locale,
                    TermText.path == path,
                    TermText.status == "published",
                )
            )
            if row is not None:
                return s.get(Term, row.owner_id), None
        t = s.scalar(select(Term).where(Term.path == path))
        if t is not None:
            if wanted(registry, locale):
                own = _published(s, TermText, [t.id], locale).get(t.id)
                if own is not None and own.path and own.path != path:
                    return None, own.path
            return t, None
        row = s.scalar(
            select(TermText).where(TermText.path == path, TermText.locale != default).limit(1)
        )
        if row is None:
            return None, None
        t = s.get(Term, row.owner_id)
        if t is None:
            return None, None
        if wanted(registry, locale):
            own = _published(s, TermText, [t.id], locale).get(t.id)
            if own is not None and own.path:
                return None, own.path
        return None, t.path or None


def entry_alternates(
    db: Any, registry: Registry, e: Entry, home: bool = False
) -> dict[str, str | None]:
    """Where an entry is in each language (None: not translated there), for hreflang."""
    if home:
        return dict.fromkeys(registry.languages, "/")
    out: dict[str, str | None] = {registry.default_language: e.path}
    with db.session() as s:
        rows = s.scalars(
            select(EntryText).where(
                EntryText.owner_id == e.id,
                EntryText.locale.in_(others(registry)),
                EntryText.status == "published",
            )
        )
        found = {r.locale: r.path for r in rows if r.path}
    out.update({x: found.get(x) for x in others(registry)})
    return out


def term_alternates(db: Any, registry: Registry, t: Term) -> dict[str, str | None]:
    out: dict[str, str | None] = {registry.default_language: t.path or None}
    with db.session() as s:
        rows = s.scalars(
            select(TermText).where(
                TermText.owner_id == t.id,
                TermText.locale.in_(others(registry)),
                TermText.status == "published",
            )
        )
        found = {r.locale: r.path for r in rows if r.path}
    out.update({x: found.get(x) for x in others(registry)})
    return out


# --- translated addresses ----------------------------------------------------------------------


def _slugs(s: Any, model: Any, ids: list[Any], locale: str) -> dict[Any, str]:
    """Each record's slug in ``locale``, where it has one (a draft's too: an address is
    made before its text is published)."""
    if not ids:
        return {}
    rows = s.execute(
        select(model.owner_id, model.slug).where(model.owner_id.in_(ids), model.locale == locale)
    )
    return {owner: slug for owner, slug in rows if slug}


def _term_chain(s: Any, term: Term) -> list[Term]:
    chain, seen = [term], {term.id}
    while chain[0].parent_id and chain[0].parent_id not in seen:
        parent = s.get(Term, chain[0].parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        chain.insert(0, parent)
    return chain


def _chain_in(s: Any, chain: list[Any], model: Any, locale: str) -> str:
    slugs = _slugs(s, model, [x.id for x in chain], locale)
    return "/".join(slugs.get(x.id) or x.slug for x in chain)


def _categories(s: Any, entry_id: int) -> list[int]:
    return list(
        s.scalars(
            select(EntryTerm.term_id)
            .join(Term, Term.id == EntryTerm.term_id)
            .where(EntryTerm.entry_id == entry_id, Term.taxonomy == "category")
            .order_by(EntryTerm.position)
        )
    )


def _entry_path(s: Any, registry: Registry, e: Entry, locale: str, slug: str) -> str:
    spec = registry.type(e.type)
    parents: list[Entry] = []
    parent_id, seen = e.parent_id if spec.hierarchical else None, {e.id}
    while parent_id and parent_id not in seen:
        parent = s.get(Entry, parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        parents.insert(0, parent)
        parent_id = parent.parent_id
    categories = _categories(s, e.id)
    first = s.get(Term, categories[0]) if categories else None
    return build_path(
        spec.path,
        slug=slug,
        entry_id=e.id,
        type_name=e.type,
        parent_path=_chain_in(s, parents, EntryText, locale) if parents else "",
        category=_chain_in(s, _term_chain(s, first), TermText, locale) if first else "",
        when=e.published_at or e.created_at,
    )


def _document(e: Entry, row: Any, registry: Registry) -> tuple[str, str, Document | None]:
    """What the search index holds of an entry in a language: a document, or None (out)."""
    from nest_content.service import text_of  # noqa: PLC0415 - service imports this module

    kind = kind_for(row.locale if row is not None else "", registry)
    if row is None or e.status != "published" or row.status != "published" or not row.path:
        return kind, str(e.id), None
    body = " ".join(x for x in (text_of(row.excerpt), text_of(row.body)) if x)
    return (
        kind,
        str(e.id),
        Document(
            kind=kind,
            id=str(e.id),
            title=row.title or e.title,
            body=body,
            url=row.path,
            scope=e.type,
        ),
    )


def refresh_entries(
    s: Any, registry: Registry, entry_ids: list[int], locales: list[str] | None = None
) -> list[tuple[str, str, Document | None]]:
    """The translated slugs and addresses of these entries (and of their children's, for
    pages under pages) made again, in ``locales`` (all but the default); what the search
    index should now hold of each, per language."""
    wanted_locales = [x for x in (locales or others(registry)) if x != registry.default_language]
    if not wanted_locales or not entry_ids:
        return []
    out: list[tuple[str, str, Document | None]] = []
    done: set[tuple[int, str]] = set()
    frontier = list(dict.fromkeys(entry_ids))
    with s.no_autoflush:
        while frontier:
            e_id = frontier.pop(0)
            e = s.get(Entry, e_id)
            if e is None:
                continue
            for locale in wanted_locales:
                if (e_id, locale) in done:
                    continue
                done.add((e_id, locale))
                row = s.get(EntryText, (e_id, locale))
                if row is not None:
                    base = slugify(row.slug or row.title)[:200] or e.slug
                    slug, n = base, 1
                    while True:
                        path = _entry_path(s, registry, e, locale, slug)
                        clash = s.scalar(
                            select(EntryText.owner_id).where(
                                EntryText.locale == locale,
                                EntryText.path == path,
                                EntryText.owner_id != e_id,
                            )
                        )
                        if clash is None:
                            break
                        n += 1
                        slug = f"{base}-{n}"
                    row.slug, row.path = slug, path
                    # written now: the next one made in this batch sees it taken (two
                    # translations of the same title get -2, never the same address)
                    s.flush()
                out.append(
                    _document(e, row, registry)
                    if row is not None
                    else (kind_for(locale, registry), str(e_id), None)
                )
            if registry.type(e.type).hierarchical:
                frontier += list(s.scalars(select(Entry.id).where(Entry.parent_id == e_id)))
    s.flush()
    return out


def refresh_terms(
    s: Any, registry: Registry, term_ids: list[int], locales: list[str] | None = None
) -> list[tuple[str, str, Document | None]]:
    """The translated addresses of these terms, their children and their entries."""
    wanted_locales = [x for x in (locales or others(registry)) if x != registry.default_language]
    if not wanted_locales or not term_ids:
        return []
    ids, frontier = list(term_ids), list(term_ids)
    while frontier:  # and every term under them
        frontier = [
            i
            for i in s.scalars(select(Term.id).where(Term.parent_id.in_(frontier)))
            if i not in ids
        ]
        ids += frontier
    with s.no_autoflush:
        for t in s.scalars(select(Term).where(Term.id.in_(ids))):
            spec = registry.taxonomies.get(t.taxonomy)
            if spec is None:
                continue
            chain = _term_chain(s, t)
            for locale in wanted_locales:
                row = s.get(TermText, (t.id, locale))
                if row is None:
                    continue
                row.slug = slugify(row.slug or row.name)[:200] or t.slug
                parent_path = _chain_in(s, chain[:-1], TermText, locale) if len(chain) > 1 else ""
                row.path = (
                    term_path(
                        spec.path, taxonomy=t.taxonomy, slug=row.slug, parent_path=parent_path
                    )
                    or None
                )
    s.flush()
    entries = list(
        dict.fromkeys(s.scalars(select(EntryTerm.entry_id).where(EntryTerm.term_id.in_(ids))))
    )
    return refresh_entries(s, registry, entries, wanted_locales)


def apply(search: Any, documents: list[tuple[str, str, Document | None]]) -> None:
    """Put in (or take out of) the search index what :func:`refresh_entries` said."""
    shown = [d for _k, _i, d in documents if d is not None]
    if shown:
        search.index(shown)
    gone: dict[str, list[str]] = {}
    for kind, ident, d in documents:
        if d is None:
            gone.setdefault(kind, []).append(ident)
    for kind, ids in gone.items():
        search.remove(kind, ids)


def forget(search: Any, registry: Registry, entry_ids: list[int]) -> None:
    """An entry out of every language's index (trashed, deleted)."""
    for locale in others(registry):
        search.remove(kind_for(locale, registry), [str(i) for i in entry_ids])


def documents_of(
    s: Any, registry: Registry, entry_ids: list[int]
) -> list[tuple[str, str, Document | None]]:
    """What the index should hold of these entries in every other language (untrashed)."""
    out = []
    for e_id in entry_ids:
        e = s.get(Entry, e_id)
        if e is None:
            continue
        for locale in others(registry):
            row = s.get(EntryText, (e_id, locale))
            out.append(
                _document(e, row, registry)
                if row is not None
                else (kind_for(locale, registry), str(e_id), None)
            )
    return out


def reindex(db: Any, search: Any, registry: Registry) -> int:
    """Every other language's index made again."""
    done = 0
    for locale in others(registry):
        kind = kind_for(locale, registry)
        search.clear(kind)
        with db.session() as s:
            rows = s.execute(
                select(Entry, EntryText)
                .join(EntryText, EntryText.owner_id == Entry.id)
                .where(
                    EntryText.locale == locale,
                    EntryText.status == "published",
                    Entry.status == "published",
                )
            ).all()
            documents = [d for e, row in rows if (d := _document(e, row, registry)[2]) is not None]
        if documents:
            search.index(documents)
        done += len(documents)
    return done


# --- for sitemaps and feeds ---------------------------------------------------------------------


def published_texts(db: Any, registry: Registry, locale: str) -> tuple[list[Any], list[Any]]:
    """Every published entry translated into ``locale`` (published there, with its
    address), and every term translated there that holds one: [(record, its row)]."""
    with db.session() as s:
        entries = s.execute(
            select(Entry, EntryText)
            .join(EntryText, EntryText.owner_id == Entry.id)
            .where(
                Entry.status == "published",
                Entry.language == "",
                EntryText.locale == locale,
                EntryText.status == "published",
                EntryText.path.is_not(None),
            )
            .order_by(EntryText.path)
        ).all()
        used = (
            select(EntryTerm.term_id)
            .join(Entry, Entry.id == EntryTerm.entry_id)
            .where(Entry.status == "published")
        )
        terms = s.execute(
            select(Term, TermText)
            .join(TermText, TermText.owner_id == Term.id)
            .where(
                TermText.locale == locale,
                TermText.status == "published",
                TermText.path.is_not(None),
                Term.id.in_(used),
            )
            .order_by(TermText.path)
        ).all()
    return [tuple(r) for r in entries], [tuple(r) for r in terms]
