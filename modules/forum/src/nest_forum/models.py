"""The forum's tables: boards, their topics, and the topics' posts."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("forum")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Board(Base):
    __tablename__ = "forum_board"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # whose board it is: none for a public board; "<world>/<kind>:<id>" for one only its
    # members read (a settlement's assembly), as the application says (forum.access)
    scope: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # the board it is in (none: a board of the forum's own); a board in a board has the
    # same scope as the one it is in, so its members are the same
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("forum_board.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # put away: still read by those who may, written by no one, with every board in it
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Topic(Base):
    __tablename__ = "forum_topic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("forum_board.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_post_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_author_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posts: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    # put away: read, never written again, listed apart from the board's open topics
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Post(Base):
    __tablename__ = "forum_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("forum_topic.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(Integer, index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
