"""What the gallery module does with its records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select

from nest.text import slugify
from nest_gallery.models import Alias, Collection, Photo


@dataclass
class Card:
    """A collection as a tile: its title, how many photos (or galleries), a cover."""

    collection: Collection
    count: int
    cover: str
    is_album: bool


def ensure(
    db: Any,
    title: str,
    *,
    slug: str = "",
    description: str = "",
    parent_id: int | None = None,
    position: int = 0,
    cover: str = "",
    published: bool = True,
) -> Collection:
    slug = slugify(slug or title)
    with db.session() as s, s.begin():
        c = s.scalar(select(Collection).where(Collection.slug == slug))
        if c is None:
            c = Collection(slug=slug, title=title)
            s.add(c)
        c.title, c.description, c.parent_id, c.position, c.published = (
            title,
            description,
            parent_id,
            position,
            published,
        )
        c.cover = cover or c.cover
        s.flush()
        return c


def set_photos(db: Any, collection_id: int, photos: list[dict[str, Any]]) -> int:
    with db.session() as s, s.begin():
        s.execute(delete(Photo).where(Photo.collection_id == collection_id))
        for i, p in enumerate(photos):
            s.add(
                Photo(
                    collection_id=collection_id,
                    position=i,
                    key=p["key"],
                    thumb=p.get("thumb", ""),
                    caption=p.get("caption", ""),
                    alt=p.get("alt", ""),
                )
            )
    return len(photos)


def alias(db: Any, source: str, legacy_id: int, collection_id: int) -> None:
    with db.session() as s, s.begin():
        found = s.scalar(select(Alias).where(Alias.source == source, Alias.legacy_id == legacy_id))
        if found is None:
            s.add(Alias(source=source, legacy_id=legacy_id, collection_id=collection_id))
        else:
            found.collection_id = collection_id


def by_alias(db: Any, source: str, legacy_id: int) -> Collection | None:
    with db.session() as s:
        return s.scalar(
            select(Collection)
            .join(Alias, Alias.collection_id == Collection.id)
            .where(Alias.source == source, Alias.legacy_id == legacy_id, Collection.published)
        )


def by_slug(db: Any, slug: str) -> Collection | None:
    with db.session() as s:
        return s.scalar(select(Collection).where(Collection.slug == slug, Collection.published))


def by_id(db: Any, collection_id: int) -> Collection | None:
    with db.session() as s:
        return s.get(Collection, collection_id)


def published(db: Any) -> list[Collection]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Collection)
                .where(Collection.published)
                .order_by(Collection.position, Collection.title)
            )
        )


def update(
    db: Any,
    collection_id: int,
    *,
    title: str,
    description: str,
    is_published: bool,
    cover: str,
    photo_texts: dict[int, tuple[str, str]],
) -> Collection:
    """A collection's own words, and each photo's alt text and caption."""
    title = " ".join(title.split())[:300]
    if not title:
        raise ValueError("A gallery needs a title.")
    with db.session() as s, s.begin():
        c = s.get(Collection, collection_id)
        if c is None:
            raise ValueError("That gallery no longer exists.")
        c.title, c.description = title, description.strip()
        c.published, c.cover = is_published, cover.strip()[:500]
        for p in s.scalars(select(Photo).where(Photo.collection_id == collection_id)):
            if p.id in photo_texts:
                alt, caption = photo_texts[p.id]
                p.alt = " ".join(alt.split())[:300]
                p.caption = caption.strip()
        s.flush()
        return c


def photos(db: Any, collection_id: int) -> list[Photo]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Photo).where(Photo.collection_id == collection_id).order_by(Photo.position)
            )
        )


def cards(db: Any, parent_id: int | None) -> list[Card]:
    """The collections under ``parent_id`` (None: the top level), as tiles."""
    with db.session() as s:
        rows = list(
            s.scalars(
                select(Collection)
                .where(
                    Collection.parent_id.is_(parent_id)
                    if parent_id is None
                    else Collection.parent_id == parent_id,
                    Collection.published,
                )
                .order_by(Collection.position, Collection.title)
            )
        )
        ids = [c.id for c in rows]
        photo_counts = dict(
            s.execute(
                select(Photo.collection_id, func.count())
                .where(Photo.collection_id.in_(ids))
                .group_by(Photo.collection_id)
            ).all()
        )
        child_counts = dict(
            s.execute(
                select(Collection.parent_id, func.count())
                .where(Collection.parent_id.in_(ids), Collection.published)
                .group_by(Collection.parent_id)
            ).all()
        )
        out = []
        for c in rows:
            cover = c.cover or _first_cover(s, c.id)
            is_album = child_counts.get(c.id, 0) > 0
            out.append(
                Card(
                    c,
                    child_counts.get(c.id, 0) if is_album else photo_counts.get(c.id, 0),
                    cover,
                    is_album,
                )
            )
        return out


def _first_cover(s: Any, collection_id: int, depth: int = 0) -> str:
    """A collection's own first photo, or else its first child's cover (albums of albums)."""
    first = s.scalar(
        select(Photo).where(Photo.collection_id == collection_id).order_by(Photo.position).limit(1)
    )
    if first is not None:
        return (
            first.key
        )  # media makes it the tile's size; the old small thumbnail is a fallback no longer needed
    if depth > 5:
        return ""
    children = s.scalars(
        select(Collection)
        .where(Collection.parent_id == collection_id, Collection.published)
        .order_by(Collection.position, Collection.title)
    )
    for child in children:
        cover = child.cover or _first_cover(s, child.id, depth + 1)
        if cover:
            return cover
    return ""
