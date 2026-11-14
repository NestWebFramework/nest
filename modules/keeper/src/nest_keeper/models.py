"""The keeper's table: the API's tokens, kept as hashes (a token is shown once)."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("keeper")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KeeperToken(Base):
    __tablename__ = "keeper_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))  # the start of the token, to recognise it by
    digest: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of the token
    scopes: Mapped[str] = mapped_column(String(200), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
