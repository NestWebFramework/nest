"""The push module's tables: the browsers' push addresses (sealed) and what waits for them."""

from __future__ import annotations

from datetime import datetime

from nest_db import model_base
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("push")


class Subscription(Base):
    """A browser's push address: its endpoint and keys, sealed under the site's key; found
    by a hash of the endpoint (the browser sends its endpoint, never an id)."""

    __tablename__ = "push_subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the endpoint
    sealed: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[datetime] = mapped_column(DateTime)  # last scheduled for, or sent to


class Job(Base):
    """One notification waiting: when (UTC), what (sealed: title, body, address, and the
    module's own data), who may look again before it goes (a lookup's name)."""

    __tablename__ = "push_job"
    __table_args__ = (Index("ix_push_job_due", "due"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("push_subscription.id", ondelete="CASCADE"), index=True
    )
    ref: Mapped[str] = mapped_column(String(200))  # the module's own name for it (one per ref)
    due: Mapped[datetime] = mapped_column(DateTime)
    sealed: Mapped[str] = mapped_column(Text)
    recheck: Mapped[str] = mapped_column(String(80), default="")
    tries: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime)
