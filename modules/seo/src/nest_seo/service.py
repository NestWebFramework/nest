"""Reading and saving what editors said about a page; each value checked and kept short."""

from __future__ import annotations

import contextlib
import re
import weakref
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select

from nest_seo.models import Meta, MetaText, utcnow

TEXT = ("title", "description", "keywords")  # what is said per language

# Each application's default language, by its database (a weak map: an application made
# again has a new one): what is saved is mirrored in its text table, the translations'
# source.
_defaults: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()


def set_default(db: Any, language: str) -> None:
    with contextlib.suppress(TypeError):  # a database object that cannot be weakly referenced
        _defaults[db] = language


def _mirror(s: Any, db: Any, m: Meta) -> None:
    from nest_db import delete_text, save_text  # noqa: PLC0415

    default = _defaults.get(db) if db is not None else None
    if not default:
        return
    values = {f: getattr(m, f) or "" for f in TEXT}
    if any(values.values()):
        save_text(s, MetaText, m.subject, default, values, status="published")
    else:  # nothing said in words (only a picture, noindex): nothing to translate
        delete_text(s, MetaText, m.subject, default)


def text(db: Any, subject: str, locale: str) -> MetaText | None:
    """What editors said of a page in ``locale`` (published), or None."""
    if not subject or not locale:
        return None
    with db.session() as s:
        row = s.get(MetaText, (subject, locale))
        return row if row is not None and row.status == "published" else None


def backfill(db: Any, default: str) -> int:
    """The default language's rows of what was said before the text table (one statement)."""
    from sqlalchemy import exists, insert, literal, null, or_  # noqa: PLC0415

    if not default:
        return 0
    with db.session() as s, s.begin():
        has = exists().where(MetaText.owner_id == Meta.subject, MetaText.locale == default)
        said = or_(Meta.title != "", Meta.description != "", Meta.keywords != "")
        done = s.execute(
            insert(MetaText).from_select(
                ["owner_id", "locale", "status", "updated_at", "source_updated_at", *TEXT],
                select(
                    Meta.subject,
                    literal(default),
                    literal("published"),
                    Meta.updated_at,
                    null(),
                    *(getattr(Meta, f) for f in TEXT),
                ).where(~has, said),
            )
        )
    return int(done.rowcount or 0)


LIMITS = {"title": 200, "description": 400, "keywords": 400, "image": 500, "canonical": 500}
FIELDS = ("title", "description", "keywords", "image", "canonical", "noindex")


class SeoError(ValueError):
    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.message = message
        self.params = params


@dataclass
class Values:
    title: str = ""
    description: str = ""
    keywords: str = ""
    image: str = ""
    canonical: str = ""
    noindex: bool = False

    def empty(self) -> bool:
        return not any(
            (self.title, self.description, self.keywords, self.image, self.canonical, self.noindex)
        )


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def keywords(value: str) -> str:
    """Words separated by commas, each once, as they were typed."""
    seen, out = set(), []
    for word in re.split(r"[,;\n]", value or ""):
        word = " ".join(word.split())
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    return ", ".join(out)[: LIMITS["keywords"]]


def clean(raw: dict[str, Any]) -> Values:
    v = Values(
        title=_line(raw.get("title"), LIMITS["title"]),
        description=_line(raw.get("description"), LIMITS["description"]),
        keywords=keywords(str(raw.get("keywords") or "")),
        image=_line(raw.get("image"), LIMITS["image"]),
        canonical=_line(raw.get("canonical"), LIMITS["canonical"]),
        noindex=bool(raw.get("noindex"))
        and str(raw.get("noindex")).lower() not in ("0", "false", ""),
    )
    if v.image and (
        v.image.startswith(("/", "javascript:", "data:"))
        or "://" in v.image
        and not v.image.startswith("https://")
    ):
        raise SeoError("The sharing picture is a stored picture (uploads/...) or an https address.")
    if v.canonical and not (
        (v.canonical.startswith("/") and not v.canonical.startswith("//"))
        or v.canonical.startswith("https://")
    ):
        raise SeoError("The canonical address is a path on this site (/...) or an https address.")
    return v


def get(db: Any, subject: str) -> Meta | None:
    if not subject:
        return None
    with db.session() as s:
        return s.get(Meta, subject)


def many(db: Any, subjects: list[str]) -> dict[str, Meta]:
    subjects = [x for x in subjects if x]
    if not subjects:
        return {}
    with db.session() as s:
        return {m.subject: m for m in s.scalars(select(Meta).where(Meta.subject.in_(subjects)))}


def save(db: Any, subject: str, values: Values) -> Meta | None:
    """Keep ``values`` for ``subject`` (all empty: forget it)."""
    if not subject or len(subject) > 200:
        raise SeoError("A page to describe is needed.")
    with db.session() as s, s.begin():
        m = s.get(Meta, subject)
        if values.empty():
            if m is not None:
                s.delete(m)
            return None
        if m is None:
            m = Meta(subject=subject)
            s.add(m)
        for name in FIELDS:
            setattr(m, name, getattr(values, name))
        m.updated_at = utcnow()
        s.flush()
        _mirror(s, db, m)
        s.flush()
        return m


def forget(db: Any, subject: str) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Meta).where(Meta.subject == subject))


def forget_module(db: Any, module: str) -> int:
    """Every subject of a module ("gallery.collection:7" is gallery's); how many went."""
    from sqlalchemy import delete  # noqa: PLC0415

    with db.session() as s, s.begin():
        gone = s.execute(delete(Meta).where(Meta.subject.like(f"{module}.%")))
    return int(gone.rowcount or 0)
