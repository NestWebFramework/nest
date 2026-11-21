"""What editors said about a page for search engines: one row per subject."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base, text_table
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("seo")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Meta(Base):
    __tablename__ = "seo_meta"

    # the module's name and its record: "content.entry:12", "gallery.collection:3"
    subject: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(400), default="")
    keywords: Mapped[str] = mapped_column(String(400), default="")
    image: Mapped[str] = mapped_column(String(500), default="")
    canonical: Mapped[str] = mapped_column(String(500), default="")
    noindex: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")  # for editors, never shown
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# What it says of a page, in each language of the site: one row per language, the
# default one's mirroring the row above (written with it). The picture, the canonical
# address and noindex are the page's, whatever its language.
MetaText = text_table(Base, Meta, title=String(200), description=String(400), keywords=String(400))
