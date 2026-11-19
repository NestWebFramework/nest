"""What the content module does with its records, apart from HTTP.

Every write goes through here, so that what is derived stays true: an entry's
path follows its type's template, its category and its parents (and its
children's paths follow it); a published entry is in the search index and an
unpublished one is not; an edit keeps the previous version as a revision.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nest_search import Document
from sqlalchemy import delete, func, or_, select

from nest.text import slugify
from nest_content.html import sanitize
from nest_content.models import (
    STATUSES,
    Entry,
    EntryTerm,
    Media,
    Menu,
    MenuItem,
    Revision,
    Term,
    utcnow,
)
from nest_content.types import Registry, build_path, term_path

KIND = "content.entry"


class ContentError(ValueError):
    def __init__(self, message: str, **params: object):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


@dataclass
class EntryData:
    type: str
    title: str
    body: str = ""
    slug: str = ""
    status: str = "draft"
    excerpt: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    terms: dict[str, list[int]] = field(default_factory=dict)
    parent_id: int | None = None
    position: int = 0
    featured: str = ""
    published_at: datetime | None = None
    language: str = ""
    author_id: int | None = None
    legacy_id: int | None = None
    keep_slug: bool = False  # an imported slug is kept as written (old addresses)
    clean: bool = True  # sanitize the body (always, except from a trusted source)


# --- terms -------------------------------------------------------------------------


def _term_chain(s: Any, term: Term) -> list[Term]:
    chain, seen = [term], {term.id}
    while chain[0].parent_id and chain[0].parent_id not in seen:
        parent = s.get(Term, chain[0].parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        chain.insert(0, parent)
    return chain


def ensure_term(
    db: Any,
    registry: Registry,
    taxonomy: str,
    name: str,
    *,
    slug: str = "",
    parent_id: int | None = None,
    description: str = "",
    legacy_id: int | None = None,
) -> Term:
    spec = registry.taxonomies.get(taxonomy)
    if spec is None:
        raise ContentError("No taxonomy '{name}'.", name=taxonomy)
    slug = slug or slugify(name)
    with db.session() as s, s.begin():
        term = s.scalar(select(Term).where(Term.taxonomy == taxonomy, Term.slug == slug))
        if term is None:
            term = Term(taxonomy=taxonomy, slug=slug, name=name)
            s.add(term)
        term.name, term.description = name, description or term.description
        term.parent_id = parent_id if spec.hierarchical else None
        if legacy_id is not None:
            term.legacy_id = legacy_id
        s.flush()
        _refresh_term_path(s, registry, term)
        return term


def _refresh_term_path(s: Any, registry: Registry, term: Term) -> None:
    spec = registry.taxonomies[term.taxonomy]
    chain = _term_chain(s, term)
    parent_path = "/".join(t.slug for t in chain[:-1])
    term.path = term_path(
        spec.path, taxonomy=term.taxonomy, slug=term.slug, parent_path=parent_path
    )


def term_descendants(s: Any, term_id: int) -> list[int]:
    ids, frontier = [term_id], [term_id]
    while frontier:
        frontier = list(s.scalars(select(Term.id).where(Term.parent_id.in_(frontier))))
        frontier = [i for i in frontier if i not in ids]
        ids += frontier
    return ids


# --- entries -----------------------------------------------------------------------


def _category_value(s: Any, term_ids: list[int]) -> str:
    """WordPress's %category%: the first category, with its parents: "istorie/biserici"."""
    if not term_ids:
        return ""
    term = s.get(Term, term_ids[0])
    return "/".join(t.slug for t in _term_chain(s, term)) if term else ""


def _parent_slugs(s: Any, parent_id: int | None, own_id: int | None) -> str:
    slugs, seen = [], {own_id}
    while parent_id and parent_id not in seen:
        parent = s.get(Entry, parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        slugs.insert(0, parent.slug)
        parent_id = parent.parent_id
    return "/".join(slugs)


def _compute_path(s: Any, registry: Registry, e: Entry, category_ids: list[int]) -> str:
    spec = registry.type(e.type)
    return build_path(
        spec.path,
        slug=e.slug,
        entry_id=e.id,
        type_name=e.type,
        parent_path=_parent_slugs(s, e.parent_id, e.id) if spec.hierarchical else "",
        category=_category_value(s, category_ids),
        when=e.published_at or e.created_at,
    )


def _unique(s: Any, registry: Registry, e: Entry, category_ids: list[int], keep_slug: bool) -> None:
    base, n = e.slug, 1
    with s.no_autoflush:
        while True:
            e.path = _compute_path(s, registry, e, category_ids)
            clash = s.scalar(
                select(Entry.id).where(Entry.language == e.language, Entry.path == e.path)
            )
            if clash is None or clash == e.id:
                return
            n += 1
            e.slug = f"{base}-{n}"


def _snapshot(e: Entry, terms: list[int]) -> dict[str, Any]:
    return {
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "excerpt": e.excerpt,
        "body": e.body,
        "fields": e.fields,
        "terms": terms,
        "parent_id": e.parent_id,
        "featured": e.featured,
        "published_at": e.published_at.isoformat() if e.published_at else None,
    }


def save_entry(
    db: Any, search: Any, registry: Registry, data: EntryData, *, existing_id: int | None = None
) -> Entry:
    spec = registry.type(data.type)
    title = data.title.strip()
    if not title:
        raise ContentError("An entry needs a title.")
    if data.status not in STATUSES:
        raise ContentError("Unknown status '{status}'.", status=data.status)
    fields, errors = registry.validate_fields(data.type, data.fields)
    if errors:
        name, message = next(iter(errors.items()))
        raise ContentError("{field}: {problem}", field=name, problem=message)
    for taxonomy in data.terms:
        if taxonomy not in spec.taxonomies:
            raise ContentError(
                "{type} entries have no {taxonomy}.", type=data.type, taxonomy=taxonomy
            )

    with db.session() as s, s.begin():
        if existing_id is not None:
            e = s.get(Entry, existing_id)
            if e is None:
                raise ContentError("That entry no longer exists.")
            if e.status == TRASH:
                raise ContentError("That entry is in the trash; restore it first.")
            old_terms = list(s.scalars(select(EntryTerm.term_id).where(EntryTerm.entry_id == e.id)))
            if spec.revisions > 0:
                s.add(
                    Revision(entry_id=e.id, author_id=data.author_id, data=_snapshot(e, old_terms))
                )
        else:
            e = Entry(
                type=data.type,
                created_at=utcnow(),
                legacy_id=data.legacy_id,
                author_id=data.author_id,
            )
        e.title = title[:300]
        e.slug = (data.slug.strip() if data.keep_slug else slugify(data.slug or title))[
            :200
        ] or "entry"
        e.status = data.status
        e.language = data.language
        e.excerpt = data.excerpt.strip()
        e.body = sanitize(data.body) if data.clean else data.body
        e.fields = fields
        e.parent_id = data.parent_id if spec.hierarchical else None
        e.position = data.position
        e.featured = data.featured
        e.published_at = data.published_at or (
            e.published_at or utcnow() if data.status == "published" else None
        )
        e.updated_at = utcnow()
        category_ids = data.terms.get("category", [])
        _unique(s, registry, e, category_ids, data.keep_slug)
        if e.id is None:
            s.add(e)
        s.flush()
        s.execute(delete(EntryTerm).where(EntryTerm.entry_id == e.id))
        for ids in data.terms.values():
            for i, term_id in enumerate(ids):
                s.add(EntryTerm(entry_id=e.id, term_id=term_id, position=i))
        if existing_id is not None and spec.revisions > 0:
            _prune_revisions(s, e.id, spec.revisions)
        changed = _refresh_children(s, registry, e)
        s.flush()
        documents = [(x, document(x)) for x in [e, *changed]]
    _index(search, documents)
    return e


def _prune_revisions(s: Any, entry_id: int, keep: int) -> None:
    ids = list(
        s.scalars(
            select(Revision.id)
            .where(Revision.entry_id == entry_id)
            .order_by(Revision.id.desc())
            .offset(keep)
        )
    )
    if ids:
        s.execute(delete(Revision).where(Revision.id.in_(ids)))


def _refresh_children(s: Any, registry: Registry, parent: Entry) -> list[Entry]:
    """Children's paths follow their parent's slug (pages under pages)."""
    changed: list[Entry] = []
    for child in s.scalars(select(Entry).where(Entry.parent_id == parent.id)):
        categories = list(
            s.scalars(
                select(EntryTerm.term_id)
                .join(Term, Term.id == EntryTerm.term_id)
                .where(EntryTerm.entry_id == child.id, Term.taxonomy == "category")
                .order_by(EntryTerm.position)
            )
        )
        new = _compute_path(s, registry, child, categories)
        if new != child.path:
            child.path = new
            changed.append(child)
            changed += _refresh_children(s, registry, child)
    return changed


def refresh_term_entries(db: Any, search: Any, registry: Registry, term_id: int) -> int:
    """After a category's slug changes, its entries' addresses follow."""
    return len(_refresh_term_entries(db, search, registry, term_id))


def _refresh_term_entries(
    db: Any, search: Any, registry: Registry, term_id: int, extra_entries: list[int] | None = None
) -> list[tuple[str, str]]:
    """The addresses of a term, its children and their entries made again; the moves
    (old path, new path) of what was public, for redirects."""
    moves: list[tuple[str, str]] = []
    with db.session() as s, s.begin():
        ids = term_descendants(s, term_id) if s.get(Term, term_id) else []
        for t in s.scalars(select(Term).where(Term.id.in_(ids))):
            before = t.path
            _refresh_term_path(s, registry, t)
            if before and before != t.path:
                moves.append((before, t.path))
        entries = list(
            s.scalars(
                select(Entry)
                .join(EntryTerm, EntryTerm.entry_id == Entry.id)
                .where(EntryTerm.term_id.in_(ids))
            )
        )
        if extra_entries:
            known = {e.id for e in entries}
            entries += [
                e
                for e in s.scalars(select(Entry).where(Entry.id.in_(extra_entries)))
                if e.id not in known
            ]
        for e in entries:
            categories = list(
                s.scalars(
                    select(EntryTerm.term_id)
                    .join(Term, Term.id == EntryTerm.term_id)
                    .where(EntryTerm.entry_id == e.id, Term.taxonomy == "category")
                    .order_by(EntryTerm.position)
                )
            )
            before = e.path
            e.path = _compute_path(s, registry, e, categories)
            if e.status == "published" and before != e.path:
                moves.append((before, e.path))
        s.flush()
        documents = [(e, document(e)) for e in entries]
    _index(search, documents)
    return moves


# --- managing terms (categories, tags...) ----------------------------------------------


@dataclass
class TermData:
    name: str
    slug: str = ""
    parent_id: int | None = None
    description: str = ""


def save_term(
    db: Any,
    search: Any,
    registry: Registry,
    taxonomy: str,
    data: TermData,
    term_id: int | None = None,
) -> tuple[Term, list[tuple[str, str]]]:
    """A category (or a tag) made or changed; when its address changes, its entries'
    follow, and the moves are returned (old path, new path) for redirects."""
    spec = registry.taxonomies.get(taxonomy)
    if spec is None:
        raise ContentError("No taxonomy '{name}'.", name=taxonomy)
    name = " ".join(data.name.split())[:200]
    if not name:
        raise ContentError("A category needs a name.")
    slug = slugify(data.slug or name)[:200] or "categorie"
    parent_id = data.parent_id if spec.hierarchical else None
    with db.session() as s, s.begin():
        clash = s.scalar(
            select(Term).where(
                Term.taxonomy == taxonomy, Term.slug == slug, Term.id != (term_id or 0)
            )
        )
        if clash is not None:
            raise ContentError("Another one is already at the address '{slug}'.", slug=slug)
        if term_id is None:
            term = Term(taxonomy=taxonomy, slug=slug, name=name)
            s.add(term)
            s.flush()
        else:
            term = s.get(Term, term_id)
            if term is None or term.taxonomy != taxonomy:
                raise ContentError("That category no longer exists.")
            if parent_id is not None and parent_id in term_descendants(s, term.id):
                raise ContentError("A category cannot be inside itself or inside one of its own.")
        if parent_id is not None:
            parent = s.get(Term, parent_id)
            if parent is None or parent.taxonomy != taxonomy:
                raise ContentError("That parent category no longer exists.")
        moved = term_id is not None and (term.slug != slug or term.parent_id != parent_id)
        term.name, term.slug, term.parent_id = name, slug, parent_id
        term.description = data.description.strip()
        if term_id is None:
            _refresh_term_path(s, registry, term)
        s.flush()
        s.expunge(term)
    moves = _refresh_term_entries(db, search, registry, term.id) if moved else []
    return term_by_id(db, term.id) or term, moves


def delete_term(db: Any, search: Any, registry: Registry, term_id: int) -> list[tuple[str, str]]:
    """A category gone: its children move up to its parent, its entries simply lose it
    (and their addresses follow); the moves are returned, the term's own to its parent's."""
    with db.session() as s, s.begin():
        term = s.get(Term, term_id)
        if term is None:
            return []
        parent = s.get(Term, term.parent_id) if term.parent_id else None
        children = [c.id for c in s.scalars(select(Term).where(Term.parent_id == term.id))]
        entry_ids = list(s.scalars(select(EntryTerm.entry_id).where(EntryTerm.term_id == term.id)))
        own_path, target = term.path, (parent.path if parent else "/")
        for c in s.scalars(select(Term).where(Term.parent_id == term.id)):
            c.parent_id = term.parent_id
        s.execute(delete(EntryTerm).where(EntryTerm.term_id == term.id))
        s.delete(term)
    moves = [(own_path, target)] if own_path else []
    for child in children:
        moves += _refresh_term_entries(db, search, registry, child)
    if entry_ids:
        moves += _refresh_term_entries(db, search, registry, 0, extra_entries=entry_ids)
    return moves


def term_by_id(db: Any, term_id: int) -> Term | None:
    with db.session() as s:
        return s.get(Term, term_id)


def term_tree(db: Any, taxonomy: str, type_name: str | None = None) -> list[tuple[Term, int, int]]:
    """A taxonomy's terms in order, each with its depth and how many entries (of a type,
    not in the trash) it holds itself."""
    with db.session() as s:
        terms = list(s.scalars(select(Term).where(Term.taxonomy == taxonomy).order_by(Term.name)))
        q = (
            select(EntryTerm.term_id, func.count())
            .join(Entry, Entry.id == EntryTerm.entry_id)
            .where(Entry.status != TRASH)
            .group_by(EntryTerm.term_id)
        )
        if type_name:
            q = q.where(Entry.type == type_name)
        counts = dict(s.execute(q).all())
    by_parent: dict[int | None, list[Term]] = {}
    ids = {t.id for t in terms}
    for t in terms:
        by_parent.setdefault(t.parent_id if t.parent_id in ids else None, []).append(t)
    out: list[tuple[Term, int, int]] = []

    def walk(parent: int | None, depth: int) -> None:
        for t in by_parent.get(parent, []):
            out.append((t, depth, counts.get(t.id, 0)))
            walk(t.id, depth + 1)

    walk(None, 0)
    return out


def delete_entry(db: Any, search: Any, entry_id: int) -> None:
    with db.session() as s, s.begin():
        e = s.get(Entry, entry_id)
        if e is not None:
            s.delete(e)
    search.remove(KIND, [str(entry_id)])


def text_of(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).strip()


def document(e: Entry) -> Document:
    return Document(
        kind=KIND,
        id=str(e.id),
        title=e.title,
        body=" ".join(x for x in (text_of(e.excerpt), text_of(e.body)) if x),
        url=e.path,
        scope=e.type,
    )


def _index(search: Any, documents: list[tuple[Entry, Document]]) -> None:
    published = [d for e, d in documents if e.status == "published"]
    hidden = [str(e.id) for e, _d in documents if e.status != "published"]
    if published:
        search.index(published)
    if hidden:
        search.remove(KIND, hidden)


def reindex(db: Any, search: Any, batch: int = 500) -> int:
    search.clear(KIND)
    done, offset = 0, 0
    with db.session() as s:
        while True:
            rows = s.scalars(
                select(Entry)
                .where(Entry.status == "published")
                .order_by(Entry.id)
                .offset(offset)
                .limit(batch)
            ).all()
            if not rows:
                return done
            search.index([document(e) for e in rows])
            done += len(rows)
            offset += batch


# --- reading -----------------------------------------------------------------------


def entry_by_path(
    db: Any, path: str, language: str = "", *, include_unpublished: bool = False
) -> Entry | None:
    with db.session() as s:
        q = select(Entry).where(Entry.path == path, Entry.language == language)
        if not include_unpublished:
            q = q.where(Entry.status == "published")
        return s.scalar(q)


def entry(db: Any, entry_id: int) -> Entry | None:
    with db.session() as s:
        return s.get(Entry, entry_id)


def entry_by_legacy(db: Any, legacy_id: int) -> Entry | None:
    with db.session() as s:
        return s.scalar(select(Entry).where(Entry.legacy_id == legacy_id))


def term_by_path(db: Any, path: str) -> Term | None:
    with db.session() as s:
        return s.scalar(select(Term).where(Term.path == path))


def term_by(
    db: Any,
    taxonomy: str,
    *,
    legacy_id: int | None = None,
    slug: str | None = None,
    name: str | None = None,
) -> Term | None:
    with db.session() as s:
        q = select(Term).where(Term.taxonomy == taxonomy)
        if legacy_id is not None:
            q = q.where(Term.legacy_id == legacy_id)
        elif slug is not None:
            q = q.where(or_(Term.slug == slug, Term.name == (name or slug)))
        else:
            return None
        return s.scalar(q.limit(1))


def term(db: Any, term_id: int) -> Term | None:
    with db.session() as s:
        return s.get(Term, term_id)


def terms(db: Any, taxonomy: str) -> list[Term]:
    with db.session() as s:
        return list(s.scalars(select(Term).where(Term.taxonomy == taxonomy).order_by(Term.name)))


def terms_of(db: Any, entry_id: int) -> dict[str, list[Term]]:
    with db.session() as s:
        rows = s.scalars(
            select(Term)
            .join(EntryTerm, EntryTerm.term_id == Term.id)
            .where(EntryTerm.entry_id == entry_id)
            .order_by(EntryTerm.position)
        )
        out: dict[str, list[Term]] = {}
        for t in rows:
            out.setdefault(t.taxonomy, []).append(t)
        return out


def listing(
    db: Any,
    *,
    types: list[str] | None = None,
    term_id: int | None = None,
    page: int = 1,
    per_page: int = 10,
    order: str = "date",
    include_children: bool = True,
    language: str = "",
) -> tuple[list[Entry], int]:
    with db.session() as s:
        q = select(Entry).where(Entry.status == "published", Entry.language == language)
        if types:
            q = q.where(Entry.type.in_(types))
        if term_id is not None:
            ids = term_descendants(s, term_id) if include_children else [term_id]
            q = q.where(Entry.id.in_(select(EntryTerm.entry_id).where(EntryTerm.term_id.in_(ids))))
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        ordering = (
            (Entry.title,) if order == "title" else (Entry.published_at.desc(), Entry.id.desc())
        )
        rows = s.scalars(
            q.order_by(*ordering).offset((max(page, 1) - 1) * per_page).limit(per_page)
        ).all()
        return list(rows), total


def published_of_types(db: Any, types: list[str], limit: int = 5000) -> list[Entry]:
    """The published entries of these types (the places for a map, say)."""
    if not types:
        return []
    with db.session() as s:
        q = select(Entry).where(
            Entry.status == "published", Entry.language == "", Entry.type.in_(types)
        )
        return list(s.scalars(q.order_by(Entry.title).limit(limit)))


def published_entries(db: Any, language: str = "") -> list[Entry]:
    with db.session() as s:
        q = select(Entry).where(Entry.status == "published", Entry.language == language)
        return list(s.scalars(q.order_by(Entry.path)))


def sitemap(db: Any, language: str = "") -> list[tuple[str, datetime | None]]:
    """Every published address (entries, then the terms that hold any) and when it changed."""
    with db.session() as s:
        entries = s.execute(
            select(Entry.path, Entry.updated_at)
            .where(Entry.status == "published", Entry.language == language)
            .order_by(Entry.path)
        ).all()
        used = select(EntryTerm.term_id).join(Entry, Entry.id == EntryTerm.entry_id)
        used = used.where(Entry.status == "published", Entry.language == language)
        terms = s.scalars(
            select(Term.path).where(Term.path != "", Term.id.in_(used)).order_by(Term.path)
        ).all()
        return [(p, w) for p, w in entries] + [(p, None) for p in terms]


def children(db: Any, entry_id: int) -> list[Entry]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Entry)
                .where(Entry.parent_id == entry_id, Entry.status == "published")
                .order_by(Entry.position, Entry.title)
            )
        )


def entries_of_type(
    db: Any,
    type_name: str,
    *,
    q: str = "",
    page: int = 1,
    per_page: int = 50,
    term_id: int | None = None,
    without: str | None = None,
) -> tuple[list[Entry], int]:
    """A type's entries, newest change first; of a term (and its children), or without any
    term of the taxonomy ``without``."""
    with db.session() as s:
        query = select(Entry).where(Entry.type == type_name, Entry.status != TRASH)
        if term_id is not None:
            ids = term_descendants(s, term_id)
            query = query.where(
                Entry.id.in_(select(EntryTerm.entry_id).where(EntryTerm.term_id.in_(ids)))
            )
        if without:
            tagged = (
                select(EntryTerm.entry_id)
                .join(Term, Term.id == EntryTerm.term_id)
                .where(Term.taxonomy == without)
            )
            query = query.where(Entry.id.not_in(tagged))
        if q:
            query = query.where(Entry.title.ilike(f"%{q}%"))
        total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = s.scalars(
            query.order_by(Entry.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)
        )
        return list(rows), total


def counts_by_type(db: Any) -> dict[str, int]:
    with db.session() as s:
        q = select(Entry.type, func.count()).where(Entry.status != TRASH).group_by(Entry.type)
        return dict(s.execute(q).all())


# --- versions and the trash ------------------------------------------------------------
#
# Every save keeps the version it replaces (a revision, up to the type's ``revisions``).
# A version can be restored whole, or only its text; restoring is a save, so the version
# it replaces is kept too, and a restore can itself be undone. Deleting puts an entry in
# the trash (status "trash"), with its versions; from there it comes back as it was, or
# goes for good, by hand or after ``trash_days``.

TRASH = "trash"


def revision(db: Any, revision_id: int) -> Revision | None:
    with db.session() as s:
        return s.get(Revision, revision_id)


def _terms_by_taxonomy(s: Any, term_ids: list[int], allowed: list[str]) -> dict[str, list[int]]:
    """A snapshot's term ids grouped as EntryData wants them; terms gone since are left out."""
    if not term_ids:
        return {}
    found = {t.id: t.taxonomy for t in s.scalars(select(Term).where(Term.id.in_(term_ids)))}
    out: dict[str, list[int]] = {}
    for tid in term_ids:
        if found.get(tid) in allowed:
            out.setdefault(found[tid], []).append(tid)
    return out


def restore_revision(
    db: Any,
    search: Any,
    registry: Registry,
    entry_id: int,
    revision_id: int,
    *,
    author_id: int | None = None,
    only_body: bool = False,
) -> Entry:
    """A version made current again (or only its text, the rest as it is now)."""
    rev, current = revision(db, revision_id), entry(db, entry_id)
    if current is None or current.status == TRASH:
        raise ContentError("That entry no longer exists.")
    if rev is None or rev.entry_id != entry_id:
        raise ContentError("That version no longer exists.")
    spec = registry.type(current.type)
    snap = rev.data
    with db.session() as s:
        now_terms = _terms_by_taxonomy(
            s,
            list(s.scalars(select(EntryTerm.term_id).where(EntryTerm.entry_id == entry_id))),
            spec.taxonomies,
        )
        then_terms = _terms_by_taxonomy(s, snap.get("terms") or [], spec.taxonomies)
    if only_body:
        source = {
            "title": current.title,
            "slug": current.slug,
            "status": current.status,
            "excerpt": current.excerpt,
            "fields": current.fields,
            "parent_id": current.parent_id,
            "featured": current.featured,
            "published_at": current.published_at,
        }
        terms = now_terms
    else:
        when = snap.get("published_at")
        source = {**snap, "published_at": datetime.fromisoformat(when) if when else None}
        terms = then_terms
    status = source.get("status") if source.get("status") in STATUSES else "draft"
    return save_entry(
        db,
        search,
        registry,
        EntryData(
            type=current.type,
            title=source.get("title") or current.title,
            slug=source.get("slug") or current.slug,
            status=status,
            excerpt=source.get("excerpt") or "",
            body=snap.get("body") or "",
            fields=dict(source.get("fields") or {}),
            terms=terms,
            parent_id=source.get("parent_id"),
            featured=source.get("featured") or "",
            published_at=source.get("published_at"),
            author_id=author_id,
            language=current.language,
            keep_slug=True,
        ),
        existing_id=entry_id,
    )


def trash_entry(
    db: Any, search: Any, entry_id: int, *, author_id: int | None = None
) -> Entry | None:
    """Into the trash, with its versions and a last one of how it was (to come back as)."""
    with db.session() as s, s.begin():
        e = s.get(Entry, entry_id)
        if e is None or e.status == TRASH:
            return e
        terms = list(s.scalars(select(EntryTerm.term_id).where(EntryTerm.entry_id == e.id)))
        s.add(Revision(entry_id=e.id, author_id=author_id, data=_snapshot(e, terms)))
        e.status = TRASH
        e.updated_at = utcnow()  # when it was put in the trash
        s.flush()
    search.remove(KIND, [str(entry_id)])
    return e


def untrash_entry(db: Any, search: Any, entry_id: int) -> Entry | None:
    """Out of the trash, with the status it had."""
    with db.session() as s, s.begin():
        e = s.get(Entry, entry_id)
        if e is None or e.status != TRASH:
            return e
        last = s.scalar(
            select(Revision).where(Revision.entry_id == e.id).order_by(Revision.id.desc()).limit(1)
        )
        before = (last.data or {}).get("status") if last else None
        e.status = before if before in STATUSES else "draft"
        e.updated_at = utcnow()
        s.flush()
        documents = [(e, document(e))]
    _index(search, documents)
    return e


def trashed(db: Any, type_name: str | None = None) -> list[Entry]:
    with db.session() as s:
        q = select(Entry).where(Entry.status == TRASH)
        if type_name:
            q = q.where(Entry.type == type_name)
        return list(s.scalars(q.order_by(Entry.updated_at.desc())))


def empty_trash(db: Any, search: Any, *, older_than_days: int = 0) -> int:
    """Delete for good what has been in the trash longer than that; how many went."""
    from datetime import timedelta  # noqa: PLC0415

    limit = utcnow() - timedelta(days=max(0, older_than_days))
    with db.session() as s:
        ids = list(
            s.scalars(select(Entry.id).where(Entry.status == TRASH, Entry.updated_at <= limit))
        )
    for entry_id in ids:
        delete_entry(db, search, entry_id)
    return len(ids)


def revisions(db: Any, entry_id: int) -> list[Revision]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Revision).where(Revision.entry_id == entry_id).order_by(Revision.id.desc())
            )
        )


# --- media -------------------------------------------------------------------------


def add_media(
    db: Any,
    storage: Any,
    key: str,
    data: Any,
    *,
    filename: str = "",
    alt: str = "",
    title: str = "",
    content_type: str = "",
    legacy_id: int | None = None,
) -> Media:
    stat = storage.put(key, data, content_type)
    with db.session() as s, s.begin():
        m = s.scalar(select(Media).where(Media.key == stat.key))
        if m is None:
            m = Media(key=stat.key, filename=filename or stat.key.rsplit("/", 1)[-1])
            s.add(m)
        m.content_type = content_type or stat.content_type
        m.size, m.alt, m.title = stat.size, alt or m.alt, title or m.title
        if legacy_id is not None:
            m.legacy_id = legacy_id
        s.flush()
        return m


IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def sniff_image(head: bytes) -> str | None:
    """A picture's type from its first bytes (what it is, not what it claims to be)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def upload_key(db: Any, filename: str, content_type: str, now: datetime | None = None) -> str:
    """Where an uploaded picture goes: uploads/<year>/<month>/<its name, made safe>, made
    unique with -2, -3... (WordPress's layout, so imported and new pictures sit together)."""
    now = now or datetime.now()
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    stem = slugify(stem)[:80] or "imagine"
    ext = IMAGE_TYPES[content_type]
    folder = f"uploads/{now:%Y}/{now:%m}"
    key, n = f"{folder}/{stem}.{ext}", 1
    while media_by_key(db, key) is not None:
        n += 1
        key = f"{folder}/{stem}-{n}.{ext}"
    return key


def media_list(db: Any, q: str = "", *, images: bool = True, limit: int = 60) -> list[Media]:
    """The newest stored files (pictures only, by default), those whose name or alt holds q."""
    with db.session() as s:
        query = select(Media)
        if images:
            query = query.where(Media.content_type.like("image/%"))
        if q:
            like = f"%{q.lower()}%"
            query = query.where(
                func.lower(Media.filename).like(like) | func.lower(Media.alt).like(like)
            )
        return list(
            s.scalars(query.order_by(Media.created_at.desc(), Media.id.desc()).limit(limit))
        )


def media_by_key(db: Any, key: str) -> Media | None:
    with db.session() as s:
        return s.scalar(select(Media).where(Media.key == key))


def media_by_legacy(db: Any, legacy_id: int) -> Media | None:
    with db.session() as s:
        return s.scalar(select(Media).where(Media.legacy_id == legacy_id))


# --- menus -------------------------------------------------------------------------


@dataclass
class MenuNode:
    title: str
    url: str
    new_window: bool = False
    children: list[MenuNode] = field(default_factory=list)


def ensure_menu(db: Any, slug: str, title: str) -> Menu:
    with db.session() as s, s.begin():
        m = s.scalar(select(Menu).where(Menu.slug == slug))
        if m is None:
            m = Menu(slug=slug, title=title)
            s.add(m)
        m.title = title
        s.flush()
        return m


def add_menu_item(
    db: Any,
    menu_id: int,
    *,
    title: str = "",
    url: str = "",
    entry_id: int | None = None,
    term_id: int | None = None,
    parent_id: int | None = None,
    position: int = 0,
    new_window: bool = False,
) -> MenuItem:
    with db.session() as s, s.begin():
        item = MenuItem(
            menu_id=menu_id,
            title=title,
            url=url,
            entry_id=entry_id,
            term_id=term_id,
            parent_id=parent_id,
            position=position,
            new_window=new_window,
        )
        s.add(item)
        s.flush()
        return item


def clear_menu(db: Any, menu_id: int) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(MenuItem).where(MenuItem.menu_id == menu_id))


def menu_tree(db: Any, slug: str) -> list[MenuNode]:
    """A menu as nested nodes, with each item's title and address resolved."""
    with db.session() as s:
        menu = s.scalar(select(Menu).where(Menu.slug == slug))
        if menu is None and slug == "main":  # a site whose menu has another name
            menu = s.scalar(select(Menu).order_by(Menu.id).limit(1))
        if menu is None:
            return []
        items = list(
            s.scalars(
                select(MenuItem).where(MenuItem.menu_id == menu.id).order_by(MenuItem.position)
            )
        )
        entries = {
            e.id: e
            for e in s.scalars(
                select(Entry).where(Entry.id.in_([i.entry_id for i in items if i.entry_id]))
            )
        }
        terms_ = {
            t.id: t
            for t in s.scalars(
                select(Term).where(Term.id.in_([i.term_id for i in items if i.term_id]))
            )
        }
    nodes: dict[int, MenuNode] = {}
    roots: list[MenuNode] = []
    for item in items:
        title, url = item.title, item.url
        if item.entry_id:
            e = entries.get(item.entry_id)
            if e is None or e.status != "published":
                continue
            title, url = title or e.title, e.path
        elif item.term_id:
            t = terms_.get(item.term_id)
            if t is None:
                continue
            title, url = title or t.name, t.path
        nodes[item.id] = MenuNode(title=title, url=url or "#", new_window=item.new_window)
    for item in items:
        node = nodes.get(item.id)
        if node is None:
            continue
        parent = nodes.get(item.parent_id) if item.parent_id else None
        (parent.children if parent else roots).append(node)
    return roots
