"""The auth module's tables: accounts and the sessions signed in with them."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("auth")


def utcnow() -> datetime:
    """Naive UTC: what every engine stores and gives back alike."""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "auth_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # none for an account kept by its devices and passkeys alone (the keys module)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Session(Base):
    """A signed-in browser. The id is the SHA-256 of the cookie's token, never the token."""

    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_user.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    # a device's session slides by its own days (a year), others by the site's setting
    slide_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Failure(Base):
    """A failed sign-in: the SHA-256 of (email, address), and when. Kept for the window only."""

    __tablename__ = "auth_failure"
    __table_args__ = (Index("ix_auth_failure_key_at", "key", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
