"""The scheduler's tables: each job's state (when it runs next, how it went last), its
runs (pruned after history_days), and the lease: which process runs the jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("scheduler")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SchedulerJob(Base):
    __tablename__ = "scheduler_job"

    key: Mapped[str] = mapped_column(String(130), primary_key=True)  # <package>.<name>
    next_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    run_now: Mapped[bool] = mapped_column(Boolean, default=False)  # asked in the admin panel
    running_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_result: Mapped[str] = mapped_column(Text, default="")
    failures: Mapped[int] = mapped_column(Integer, default=0)  # in a row


class SchedulerRun(Base):
    __tablename__ = "scheduler_run"
    __table_args__ = (Index("ix_scheduler_run_key_started", "key", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(130))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    why: Mapped[str] = mapped_column(String(20), default="due")  # due, start, catch-up, asked
    result: Mapped[str] = mapped_column(Text, default="")


class SchedulerLease(Base):
    __tablename__ = "scheduler_lease"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    holder: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
