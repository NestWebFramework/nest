"""The redirects table."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("redirects")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Redirect(Base):
    __tablename__ = "redirects_redirect"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(500), unique=True)
    target: Mapped[str] = mapped_column(String(1000))
    status: Mapped[int] = mapped_column(Integer, default=301)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_hit: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
