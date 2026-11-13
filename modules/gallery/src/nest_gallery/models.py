"""The gallery module's tables: galleries (an album is a gallery of galleries) and photos."""

from __future__ import annotations

from nest_db import model_base
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("gallery")


class Collection(Base):
    """A gallery of photos, or an album whose children are galleries."""

    __tablename__ = "gallery_collection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("gallery_collection.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    cover: Mapped[str] = mapped_column(String(500), default="")
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class Photo(Base):
    __tablename__ = "gallery_photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_collection.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(500))
    thumb: Mapped[str] = mapped_column(String(500), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    alt: Mapped[str] = mapped_column(String(300), default="")


class Alias(Base):
    """What a collection was called before: a plugin's gallery or shortcode id."""

    __tablename__ = "gallery_alias"
    __table_args__ = (UniqueConstraint("source", "legacy_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    legacy_id: Mapped[int] = mapped_column(Integer)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_collection.id", ondelete="CASCADE")
    )
