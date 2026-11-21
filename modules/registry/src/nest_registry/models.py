"""The registry's tables: the packages (a name, its owner), their releases (a version and
what its manifest says), the files of each release, and the tokens publishers present."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nest_db import model_base
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("registry")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Package(Base):
    """A name, owned by the account that first published it."""

    __tablename__ = "registry_package"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)  # the Nest name (forum)
    dist: Mapped[str] = mapped_column(String(160), unique=True)  # normalised (nest-forum)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)  # the auth module's account
    index_only: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # no manifest: not in the catalog
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Release(Base):
    """One version of a package, and what its manifest says it is."""

    __tablename__ = "registry_release"
    __table_args__ = (
        UniqueConstraint("package_id", "version", name="uq_registry_release_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("registry_package.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(40))
    ecosystem: Mapped[str] = mapped_column(String(40), default="nest")
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    nest: Mapped[str] = mapped_column(String(60))  # the nest-core versions it works with
    requires_python: Mapped[str] = mapped_column(String(60), default="")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    about: Mapped[str] = mapped_column(Text, default="")  # its manifest's opening comment
    screenshot: Mapped[str] = mapped_column(String(400), default="")  # a theme's, in storage
    uploader_id: Mapped[int] = mapped_column(Integer)
    yanked: Mapped[bool] = mapped_column(Boolean, default=False)
    yank_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class File(Base):
    """A wheel or a source archive of a release; never replaced once published."""

    __tablename__ = "registry_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("registry_release.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # wheel | sdist
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(400))  # where nest.storage keeps it
    signature: Mapped[str] = mapped_column(String(200), default="")  # Ed25519, base64
    signer: Mapped[str] = mapped_column(String(80), default="")  # the public key that signed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Token(Base):
    """What a publisher presents: kept as its SHA-256 only."""

    __tablename__ = "registry_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(12))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Namespace(Base):
    """The first segment of package ids (acme in acme.module.widgets): owned by the account
    that first published in it, so nobody publishes under another's name."""

    __tablename__ = "registry_namespace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Maintainer(Base):
    """An account the owner lets publish new versions of a package."""

    __tablename__ = "registry_maintainer"
    __table_args__ = (
        UniqueConstraint("package_id", "user_id", name="uq_registry_maintainer_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("registry_package.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SigningKey(Base):
    """A public key an account signs what it publishes with (nest keygen)."""

    __tablename__ = "registry_signing_key"
    __table_args__ = (UniqueConstraint("user_id", "public", name="uq_registry_signing_key_public"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))
    public: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
