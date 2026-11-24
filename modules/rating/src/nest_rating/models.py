"""The rating module's tables: each vote, and each subject's summary (kept with the votes)."""

from __future__ import annotations

from datetime import datetime

from nest_db import model_base
from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("rating")


class Vote(Base):
    """One visitor's vote on one subject: stars 1-5, helpful 1 (yes) / -1 (no), updown 1 / -1."""

    __tablename__ = "rating_vote"
    __table_args__ = (
        UniqueConstraint("subject", "voter", name="uq_rating_vote_subject_voter"),
        Index("ix_rating_vote_subject_print", "subject", "print"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[int] = mapped_column(Integer)
    voter: Mapped[str] = mapped_column(String(40))  # the cookie's id, or "u:<user id>"
    print: Mapped[str] = mapped_column(String(32), default="")  # a day's hash of address+browser
    created: Mapped[datetime] = mapped_column(DateTime)
    updated: Mapped[datetime] = mapped_column(DateTime, index=True)


class Summary(Base):
    """A subject's votes summed up: count, sum, the stars' distribution, up and down."""

    __tablename__ = "rating_summary"

    subject: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)  # the sum of the values
    up: Mapped[int] = mapped_column(Integer, default=0)  # yes / ▲ (helpful, updown)
    down: Mapped[int] = mapped_column(Integer, default=0)
    stars: Mapped[list] = mapped_column(JSON, default=list)  # how many gave 1..5
    closed: Mapped[bool] = mapped_column(Boolean, default=False)  # no more votes taken
    updated: Mapped[datetime] = mapped_column(DateTime)
