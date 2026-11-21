"""What the gallery module does with its records."""

from __future__ import annotations

import contextlib
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select

from nest.text import slugify
from nest_gallery import texts
from nest_gallery.models import Alias, Collection, CollectionText, Photo, PhotoText

# Each application's default language, by its database (an application made again has a
# new one): what is written is mirrored in the text tables, the translations' source.
_defaults: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()


def set_default(db: Any, language: str) -> None:
    with contextlib.suppress(TypeError):  # a database object that cannot be weakly referenced
        _defaults[db] = language


def _says(p: Any) -> bool:
    return bool(texts.alt(p.alt) or texts.describes(p.caption))


def _mirror(s: Any, db: Any, collection: Collection | None = None, photos: list[Any] = ()) -> None:
    from nest_db import delete_text, save_text  # noqa: PLC0415

    default = _defaults.get(db)
    if not default:
        return
    if collection is not None and collection.id is not None:
        values = {"title": collection.title or "", "description": collection.description or ""}
        save_text(s, CollectionText, collection.id, default, values, status="published")
    for p in photos:
        if p.id is None:
            continue
        if _says(p):
            values = {"caption": p.caption or "", "alt": p.alt or ""}
            save_text(s, PhotoText, p.id, default, values, status="published")
        else:
            delete_text(s, PhotoText, p.id, default)


def backfill(db: Any, default: str) -> int:
    """The default language's rows of what was written before the text tables."""
    from nest_db import save_text  # noqa: PLC0415
    from sqlalchemy import exists, literal, null  # noqa: PLC0415
    from sqlalchemy import insert as insert_  # noqa: PLC0415

    if not default:
        return 0
    made = 0
    with db.session() as s, s.begin():
        has = exists().where(
            CollectionText.owner_id == Collection.id, CollectionText.locale == default
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        made += int(
            s.execute(
                insert_(CollectionText).from_select(
                    [
                        "owner_id",
                        "locale",
                        "status",
                        "updated_at",
                        "source_updated_at",
                        "title",
                        "description",
                    ],
                    select(
                        Collection.id,
                        literal(default),
                        literal("published"),
                        literal(now),
                        null(),
                        Collection.title,
                        Collection.description,
                    ).where(~has),
                )
            ).rowcount
            or 0
        )
        has = exists().where(PhotoText.owner_id == Photo.id, PhotoText.locale == default)
        # which photos say something is decided in Python (a file name, a camera's record)
        for p in s.scalars(select(Photo).where(~has, (Photo.caption != "") | (Photo.alt != ""))):
            if _says(p):
                save_text(
                    s,
                    PhotoText,
                    p.id,
                    default,
                    {"caption": p.caption, "alt": p.alt},
                    status="published",
                )
                made += 1
    return made


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
        _mirror(s, db, c)
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
        s.flush()
        _mirror(
            s, db, photos=list(s.scalars(select(Photo).where(Photo.collection_id == collection_id)))
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
        shown = list(s.scalars(select(Photo).where(Photo.collection_id == collection_id)))
        for p in shown:
            if p.id in photo_texts:
                alt, caption = photo_texts[p.id]
                p.alt = " ".join(alt.split())[:300]
                p.caption = caption.strip()
        s.flush()
        _mirror(s, db, c, shown)
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


# --- in another language -----------------------------------------------------------------------


def shown_cards(db: Any, cards_: list[Card], locale: str) -> list[Card]:
    """Tiles with their collections' titles in ``locale`` (the original's where none)."""
    from nest_db import overlay  # noqa: PLC0415

    default = _defaults.get(db, "")
    if not cards_ or not locale or locale == default:
        return cards_
    with db.session() as s:
        shown = overlay(s, CollectionText, [c.collection for c in cards_], locale, default)
    return [Card(o, c.count, c.cover, c.is_album) for o, c in zip(shown, cards_, strict=True)]


def shown_collection(db: Any, c: Collection, locale: str) -> Any:
    from nest_db import overlay  # noqa: PLC0415

    with db.session() as s:
        return overlay(
            s, CollectionText, [c], locale, _defaults.get(db, ""), keep_empty=("description",)
        )[0]


def shown_photos(db: Any, photos_: list[Photo], locale: str) -> list[Any]:
    """Photos with their words in ``locale``: a translated one says what it says there,
    an untranslated one the original's words."""
    from nest_db import overlay  # noqa: PLC0415

    with db.session() as s:
        return overlay(
            s, PhotoText, photos_, locale, _defaults.get(db, ""), keep_empty=("caption", "alt")
        )


def translated_collections(db: Any, locale: str) -> dict[int, Any]:
    """The collections with a published text in ``locale``: {id: its row}."""
    with db.session() as s:
        rows = s.scalars(
            select(CollectionText).where(
                CollectionText.locale == locale, CollectionText.status == "published"
            )
        )
        return {r.owner_id: r for r in rows}


# --- making and arranging, in the admin panel ------------------------------------------------

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


class GalleryError(ValueError):
    """A problem to tell an editor (to translate) with its params."""

    def __init__(self, message: str, **params: Any):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


def _descendants(s: Any, collection_id: int) -> set[int]:
    found, frontier = {collection_id}, [collection_id]
    while frontier:
        frontier = [
            i
            for i in s.scalars(select(Collection.id).where(Collection.parent_id.in_(frontier)))
            if i not in found
        ]
        found.update(frontier)
    return found


def _free_slug(s: Any, base: str, own: int | None = None) -> str:
    slug, n = base, 1
    while (
        s.scalar(select(Collection.id).where(Collection.slug == slug, Collection.id != (own or 0)))
        is not None
    ):
        n += 1
        slug = f"{base}-{n}"
    return slug


def create(db: Any, title: str, parent_id: int | None = None) -> Collection:
    """A new gallery (an album, once galleries are put in it), at the end of its parent's."""
    title = " ".join(title.split())[:300]
    if not title:
        raise GalleryError("A gallery needs a title.")
    with db.session() as s, s.begin():
        if parent_id is not None and s.get(Collection, parent_id) is None:
            raise GalleryError("That album no longer exists.")
        siblings = (
            Collection.parent_id.is_(None)
            if parent_id is None
            else Collection.parent_id == parent_id
        )
        last = s.scalar(select(func.max(Collection.position)).where(siblings))
        c = Collection(
            slug=_free_slug(s, slugify(title) or "galerie"),
            title=title,
            parent_id=parent_id,
            position=(last or 0) + 1,
            published=True,
        )
        s.add(c)
        s.flush()
        _mirror(s, db, c)
        return c


def move(db: Any, collection_id: int, parent_id: int | None) -> None:
    """Into another album (or to the top level); never into itself or one of its own."""
    with db.session() as s, s.begin():
        c = s.get(Collection, collection_id)
        if c is None:
            raise GalleryError("That gallery no longer exists.")
        if parent_id is not None:
            if parent_id in _descendants(s, collection_id):
                raise GalleryError("A gallery cannot go inside itself or inside one of its own.")
            if s.get(Collection, parent_id) is None:
                raise GalleryError("That album no longer exists.")
        c.parent_id = parent_id


def set_slug(db: Any, collection_id: int, slug: str) -> str:
    """Its address (made safe, made unique); the address it ends up with."""
    with db.session() as s, s.begin():
        c = s.get(Collection, collection_id)
        if c is None:
            raise GalleryError("That gallery no longer exists.")
        wanted = slugify(slug) or slugify(c.title) or "galerie"
        c.slug = _free_slug(s, wanted, own=c.id)
        return c.slug


def upload_key(storage: Any, filename: str, content_type: str, now: datetime | None = None) -> str:
    """Where an uploaded photo goes: uploads/<year>/<month>/<its name, made safe>, made
    unique with -2, -3... (the layout the imported photos have)."""
    now = now or datetime.now(UTC)
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    stem = slugify(stem)[:80] or "fotografie"
    ext = IMAGE_TYPES[content_type]
    folder = f"uploads/{now:%Y}/{now:%m}"
    key, n = f"{folder}/{stem}.{ext}", 1
    while storage.stat(key) is not None:
        n += 1
        key = f"{folder}/{stem}-{n}.{ext}"
    return key


def add_photo(
    db: Any,
    storage: Any,
    collection_id: int,
    filename: str,
    data: bytes,
    limit: int,
    uploaded_by: int | None = None,
) -> Photo:
    """An uploaded picture into a gallery, last: at most ``limit`` bytes, read whole and
    written again without its metadata (nest_media.clean_image: no camera, no place it
    was taken), its uploader kept."""
    from nest_media import ImageError, clean_image  # noqa: PLC0415

    if len(data) > limit:
        raise GalleryError("A photo is at most {n} MB.", n=limit // 2**20)
    with db.session() as s:
        if s.get(Collection, collection_id) is None:
            raise GalleryError("That gallery no longer exists.")
    try:
        cleaned, kind = clean_image(data)
    except ImageError as e:
        raise GalleryError(e.message, **e.params) from e
    key = upload_key(storage, filename, kind)
    storage.put(key, cleaned, kind)
    with db.session() as s, s.begin():
        last = s.scalar(
            select(func.max(Photo.position)).where(Photo.collection_id == collection_id)
        )
        p = Photo(
            collection_id=collection_id,
            position=(last if last is not None else -1) + 1,
            key=key,
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC).replace(tzinfo=None),
        )
        s.add(p)
        s.flush()
        return p


def arrange(db: Any, collection_id: int, order: list[int], remove: set[int]) -> int:
    """Its photos in ``order`` (those not named keep theirs, after), without ``remove``:
    how many were removed. Their files stay (an article may show them too)."""
    with db.session() as s, s.begin():
        photos = list(
            s.scalars(
                select(Photo)
                .where(Photo.collection_id == collection_id)
                .order_by(Photo.position, Photo.id)
            )
        )
        gone = [p for p in photos if p.id in remove]
        for p in gone:
            s.delete(p)
        kept = [p for p in photos if p.id not in remove]
        rank = {pid: i for i, pid in enumerate(order)}
        kept.sort(key=lambda p: (rank.get(p.id, len(rank)), p.position, p.id))
        for i, p in enumerate(kept):
            p.position = i
        return len(gone)


def remove_collection(db: Any, collection_id: int) -> Collection | None:
    """A gallery gone, with its photos (their files stay); its own galleries move up to its
    album. What it was, or None."""
    with db.session() as s, s.begin():
        c = s.get(Collection, collection_id)
        if c is None:
            return None
        for child in s.scalars(select(Collection).where(Collection.parent_id == c.id)):
            child.parent_id = c.parent_id
        s.execute(delete(Photo).where(Photo.collection_id == c.id))
        s.delete(c)
        s.flush()  # gone from the database before it is let go of (an expunge would undo it)
        s.expunge(c)
        return c


def tree(db: Any) -> list[tuple[Collection, int, int, int]]:
    """Every gallery in order, each with its depth, its photos and its galleries."""
    with db.session() as s:
        rows = list(s.scalars(select(Collection).order_by(Collection.position, Collection.title)))
        photos = dict(
            s.execute(select(Photo.collection_id, func.count()).group_by(Photo.collection_id)).all()
        )
    by_parent: dict[int | None, list[Collection]] = {}
    ids = {c.id for c in rows}
    for c in rows:
        by_parent.setdefault(c.parent_id if c.parent_id in ids else None, []).append(c)
    out: list[tuple[Collection, int, int, int]] = []

    def walk(parent: int | None, depth: int, seen: set[int]) -> None:
        for c in by_parent.get(parent, []):
            if c.id in seen:
                continue
            out.append((c, depth, photos.get(c.id, 0), len(by_parent.get(c.id, []))))
            walk(c.id, depth + 1, seen | {c.id})

    walk(None, 0, set())
    return out
