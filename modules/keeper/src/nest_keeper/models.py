"""The keeper's tables: its API's tokens (kept as hashes), the servers whose host helper it
talks to, the sites it watches, their checks and the actions asked of them."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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


class KeeperServer(Base):
    """A server the keeper acts on through its host helper (nest-host): this one through the
    loopback or the Docker bridge, another through its own address (a Cloudflare tunnel)."""

    __tablename__ = "keeper_server"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(300))  # the helper's address
    token: Mapped[str] = mapped_column(Text, default="")  # the helper's nh_ token, encrypted
    access_id: Mapped[str] = mapped_column(String(200), default="")  # Cloudflare Access client
    access_secret: Mapped[str] = mapped_column(Text, default="")  # its secret, encrypted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KeeperSite(Base):
    """A deployed application the keeper watches, through its agent."""

    __tablename__ = "keeper_site"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(300))  # the site's public address
    agent: Mapped[str] = mapped_column(String(300))  # its agent's address (…/_agent)
    token: Mapped[str] = mapped_column(Text, default="")  # the agent's token, encrypted
    scope: Mapped[str] = mapped_column(String(20), default="")  # what the token was last told to be
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None: not checked yet
    since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # up or down since
    status: Mapped[str] = mapped_column(Text, default="")  # its last status answer (JSON)
    problem: Mapped[str] = mapped_column(String(500), default="")
    host_site: Mapped[str] = mapped_column(String(63), default="")  # its name for nest-site
    kind: Mapped[str] = mapped_column(String(10), default="agent")  # agent, or web (an address)
    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("keeper_server.id", ondelete="SET NULL"), nullable=True
    )  # None: the helper of the keeper's settings (host_url), if any
    backup_folder: Mapped[str] = mapped_column(String(80), default="")  # under backup_dir
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # last copy
    fetch_problem: Mapped[str] = mapped_column(String(500), default="")


class KeeperCheck(Base):
    """One question to a site's agent: did it answer, how fast, what it said."""

    __tablename__ = "keeper_check"
    __table_args__ = (Index("ix_keeper_check_site_at", "site_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("keeper_site.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    up: Mapped[bool] = mapped_column(Boolean)  # answered, and said it is well
    reached: Mapped[bool] = mapped_column(Boolean)  # answered at all
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[str] = mapped_column(String(40), default="")
    problem: Mapped[str] = mapped_column(String(500), default="")


class KeeperAction(Base):
    """An action the keeper asked of a site, who asked it, and what came of it."""

    __tablename__ = "keeper_action"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("keeper_site.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    action: Mapped[str] = mapped_column(String(80))
    who: Mapped[str] = mapped_column(String(200))
    ok: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[str] = mapped_column(Text, default="")
