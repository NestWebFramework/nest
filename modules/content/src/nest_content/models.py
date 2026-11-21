"""The content module's tables."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nest_db import model_base, text_table
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("content")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Entry(Base):
    """A post, a page, or an entry of any declared type."""

    __tablename__ = "content_entry"
    __table_args__ = (UniqueConstraint("language", "path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    language: Mapped[str] = mapped_column(String(10), default="")
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    path: Mapped[str] = mapped_column(String(500))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_entry.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    featured: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class Term(Base):
    """A category, a tag, or a term of any declared taxonomy."""

    __tablename__ = "content_term"
    __table_args__ = (UniqueConstraint("taxonomy", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taxonomy: Mapped[str] = mapped_column(String(40), index=True)
    slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_term.id", ondelete="SET NULL"), nullable=True
    )
    path: Mapped[str] = mapped_column(String(500), default="", index=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class EntryTerm(Base):
    __tablename__ = "content_entry_term"

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("content_entry.id", ondelete="CASCADE"), primary_key=True
    )
    term_id: Mapped[int] = mapped_column(
        ForeignKey("content_term.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class Revision(Base):
    __tablename__ = "content_revision"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("content_entry.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Media(Base):
    """A stored file: its key in nest.storage and what a page needs to show it."""

    __tablename__ = "content_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(500), unique=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    alt: Mapped[str] = mapped_column(String(300), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)  # who, in the editor


class Menu(Base):
    __tablename__ = "content_menu"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class MenuItem(Base):
    __tablename__ = "content_menu_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    menu_id: Mapped[int] = mapped_column(
        ForeignKey("content_menu.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_menu_item.id", ondelete="CASCADE"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_entry.id", ondelete="CASCADE"), nullable=True
    )
    term_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_term.id", ondelete="CASCADE"), nullable=True
    )
    new_window: Mapped[bool] = mapped_column(Boolean, default=False)


# Each record's text in every language: one row per language, the default one included
# (a mirror of the columns above, which the default language's pages read, so its pages
# need no join). A translated address (path) is made from the translated slugs of the
# entry, its category and its parents, like the default one; NULL until it is made.
EntryText = text_table(
    Base,
    Entry,
    title=String(300),
    slug=String(200),
    path=mapped_column(String(500), nullable=True),
    excerpt=Text,
    body=Text,
    unique=("path",),
)
TermText = text_table(
    Base,
    Term,
    name=String(200),
    slug=String(200),
    path=mapped_column(String(500), nullable=True),
    description=Text,
    index=("path",),
)
# a menu item's own label (an item that links an entry or a term shows that one's title
# when it has none) and, for a link of its own, its address
MenuItemText = text_table(Base, MenuItem, title=String(200), url=String(1000))

STATUSES = ("draft", "published", "private")
