"""Accounts and server-side sessions, on whatever database the application bound.

The browser holds a random token; the database holds only its SHA-256, so a
leaked database does not hand out sessions. A session slides forward while it
is used and ends at logout, on expiry, or when the account is disabled.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select

from nest_auth.models import Session, User, utcnow
from nest_auth.passwords import (
    MAX_PASSWORD,
    dummy_hash,
    hash_password,
    needs_rehash,
    verify_password,
)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
SLIDE_AFTER = timedelta(hours=1)


class AccountError(ValueError):
    """A refusal a person can act on; its message is translated where it is shown."""

    def __init__(self, message: str, **params: object):
        self.message = message
        self.params = params
        super().__init__(message.format(**params) if params else message)


@dataclass(frozen=True)
class CurrentUser:
    """Who is signed in: a plain value, detached from any database session."""

    id: int
    email: str
    name: str
    roles: frozenset[str]

    @property
    def label(self) -> str:
        return self.name or self.email

    def has(self, *roles: str) -> bool:
        return "admin" in self.roles or any(r in self.roles for r in roles)


def _current(user: User) -> CurrentUser:
    roles = frozenset(r for r in (user.roles or "").split(",") if r)
    return CurrentUser(id=user.id, email=user.email, name=user.name or "", roles=roles)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def count_users(db: Any) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(User)) or 0


def create_user(
    db: Any,
    email: str,
    password: str,
    *,
    name: str = "",
    roles: tuple[str, ...] = (),
    min_length: int = 10,
) -> CurrentUser:
    email = normalize_email(email)
    if not _EMAIL.match(email) or len(email) > 254:
        raise AccountError("That does not look like an email address.")
    if len(password) < min_length:
        raise AccountError("A password has at least {n} characters.", n=min_length)
    if len(password) > MAX_PASSWORD:
        raise AccountError("That password is too long.")
    with db.session() as s, s.begin():
        if s.scalar(select(User.id).where(User.email == email)) is not None:
            raise AccountError("An account with this email already exists.")
        user = User(
            email=email,
            name=name.strip()[:120],
            password_hash=hash_password(password),
            roles=",".join(sorted(set(roles))),
            active=True,
            created_at=utcnow(),
        )
        s.add(user)
        s.flush()
        return _current(user)


def authenticate(db: Any, email: str, password: str) -> CurrentUser | None:
    """The account, if the password is right and the account active; None otherwise."""
    email = normalize_email(email)
    with db.session() as s, s.begin():
        user = s.scalar(select(User).where(User.email == email))
        ok = verify_password(password, user.password_hash if user else dummy_hash())
        if not (ok and user and user.active):
            return None
        user.last_login_at = utcnow()
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return _current(user)


def open_session(db: Any, user: CurrentUser, *, days: int, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with db.session() as s, s.begin():
        s.execute(delete(Session).where(Session.user_id == user.id, Session.expires_at < now))
        s.add(
            Session(
                id=token_id(token),
                user_id=user.id,
                created_at=now,
                expires_at=now + timedelta(days=days),
                last_seen_at=now,
                user_agent=user_agent[:200],
            )
        )
    return token


def user_for(db: Any, token: str, *, days: int) -> CurrentUser | None:
    if not token or len(token) > 128:
        return None
    now = utcnow()
    with db.session() as s, s.begin():
        session = s.get(Session, token_id(token))
        if session is None:
            return None
        if session.expires_at <= now:
            s.delete(session)
            return None
        user = s.get(User, session.user_id)
        if user is None or not user.active:
            s.delete(session)
            return None
        if now - session.last_seen_at > SLIDE_AFTER:
            session.last_seen_at = now
            session.expires_at = now + timedelta(days=days)
        return _current(user)


def close_session(db: Any, token: str) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Session).where(Session.id == token_id(token)))


def close_all_sessions(db: Any, user_id: int) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Session).where(Session.user_id == user_id))
