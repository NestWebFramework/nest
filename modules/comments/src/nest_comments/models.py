"""The comments module's table."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("comments")

STATUSES = ("pending", "approved", "spam", "deleted")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Comment(Base):
    """A comment on a subject: any record of any module, named "module.kind:id"."""

    __tablename__ = "comments_comment"
    __table_args__ = (UniqueConstraint("legacy_source", "legacy_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(120), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments_comment.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_name: Mapped[str] = mapped_column(String(120))
    author_email: Mapped[str] = mapped_column(String(254), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    address: Mapped[str] = mapped_column(String(64), default="")
    legacy_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
