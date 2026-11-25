"""The keys module's tables. Nothing here can be used if it leaks: the account's key and a
pairing's link are kept as their SHA-256 (random, long), a pairing's 6 digits too (short,
but valid 10 minutes, five tries)."""

from __future__ import annotations

from datetime import UTC, datetime

from nest_db import model_base
from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("keys")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountKey(Base):
    """The account's key: a link (and its code) that signs in any device, until replaced."""

    __tablename__ = "keys_account_key"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 of the code
    user_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)  # auth's account
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    saved: Mapped[int] = mapped_column(Integer, default=0)  # the player said it is saved


class Pairing(Base):
    """A device being added: from a signed-in one, a link and a 6-digit code, 10 minutes."""

    __tablename__ = "keys_pairing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    link: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of the link's token
    code: Mapped[str] = mapped_column(String(64), index=True)  # SHA-256 of the 6 digits
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    tries: Mapped[int] = mapped_column(Integer, default=0)


class Passkey(Base):
    """A passkey (WebAuthn): its id and public key; the private key never leaves the device
    (or the person's Apple, Google, Microsoft account that syncs it)."""

    __tablename__ = "keys_passkey"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # credential id, base64url
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[str] = mapped_column(String(120), default="")
    name: Mapped[str] = mapped_column(String(120), default="")
    synced: Mapped[int] = mapped_column(
        Integer, default=0
    )  # backed up (synced) or this device only
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Challenge(Base):
    """A WebAuthn ceremony under way: its challenge, for five minutes, used once."""

    __tablename__ = "keys_challenge"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 of the ticket
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    purpose: Mapped[str] = mapped_column(String(10))  # register, enter
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class DevicePin(Base):
    """A device's PIN: it locks this device's session after some idle hours, and unlocks only
    that session (never a way in from elsewhere). Hashed (scrypt); five wrong tries lock it
    a while, ten sign the device out."""

    __tablename__ = "keys_device_pin"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # the session's id
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    tries: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
