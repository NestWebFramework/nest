"""Accounts and server-side sessions, on whatever database the application bound.

The browser holds a random token; the database holds only its SHA-256, so a
leaked database does not hand out sessions. A session slides forward while it
is used and ends at logout, on expiry, or when the account is disabled.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from nest_auth.models import Session, User, utcnow
from nest_auth.passwords import (
    MAX_PASSWORD,
    dummy_hash,
    hash_password,
    needs_rehash,
    verify_password,
    weak,
)

WRONG_CURRENT = "The current password is not right."
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
    if why := weak(password, email):
        raise AccountError(why)
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


def close_other_sessions(db: Any, user_id: int, keep_token: str) -> None:
    """Sign a member out everywhere but here (after a new password, say)."""
    with db.session() as s, s.begin():
        s.execute(
            delete(Session).where(Session.user_id == user_id, Session.id != token_id(keep_token))
        )


def rename(db: Any, user_id: int, name: str) -> None:
    """A member's own name, as an account shows it (an application may name it otherwise)."""
    with db.session() as s, s.begin():
        user = s.get(User, user_id)
        if user is None:
            raise AccountError("That account no longer exists.")
        user.name = name.strip()[:120]


def change_password(db: Any, user_id: int, current: str, new: str, *, min_length: int = 10) -> None:
    """A member's new password, given the one they have."""
    if len(new) < min_length:
        raise AccountError("A password has at least {n} characters.", n=min_length)
    if len(new) > MAX_PASSWORD:
        raise AccountError("That password is too long.")
    with db.session() as s, s.begin():
        user = s.get(User, user_id)
        if user is None or not verify_password(current, user.password_hash):
            raise AccountError(WRONG_CURRENT)
        if why := weak(new, user.email):
            raise AccountError(why)
        user.password_hash = hash_password(new)


def users_by_ids(db: Any, ids: list[int]) -> dict[int, CurrentUser]:
    """Members by id, for modules that show who wrote what."""
    if not ids:
        return {}
    with db.session() as s:
        return {u.id: _current(u) for u in s.scalars(select(User).where(User.id.in_(set(ids))))}


def active_user(db: Any, user_id: int) -> CurrentUser | None:
    """A member by id if the account is active (a disabled one acts for nobody: its API
    tokens, say, stop working)."""
    with db.session() as s:
        user = s.get(User, user_id)
        return _current(user) if user is not None and user.active else None


def find_user(db: Any, who: str) -> CurrentUser | None:
    """An active member by email, or by name when only one has it."""
    who = (who or "").strip()
    if not who:
        return None
    with db.session() as s:
        user = s.scalar(select(User).where(User.email == normalize_email(who), User.active))
        if user is None:
            matches = list(
                s.scalars(
                    select(User).where(func.lower(User.name) == who.lower(), User.active).limit(2)
                )
            )
            user = matches[0] if len(matches) == 1 else None
        return _current(user) if user else None


# -- the users page of the admin panel --

ROLE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


@dataclass
class Account:
    """An account as the admin panel shows it."""

    id: int
    email: str
    name: str
    roles: tuple[str, ...]
    active: bool
    created_at: datetime
    last_login_at: datetime | None


def _account(u: User) -> Account:
    return Account(
        u.id,
        u.email,
        u.name,
        tuple(r for r in (u.roles or "").split(",") if r),
        u.active,
        u.created_at,
        u.last_login_at,
    )


def list_accounts(
    db: Any, q: str = "", *, limit: int = 50, offset: int = 0
) -> tuple[list[Account], int]:
    """Accounts, newest first, those whose email or name holds ``q``; and how many there are."""
    with db.session() as s:
        query = select(User)
        if q:
            like = f"%{q.lower()}%"
            query = query.where(
                func.lower(User.email).like(like) | func.lower(User.name).like(like)
            )
        total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = s.scalars(query.order_by(User.id.desc()).limit(limit).offset(offset))
        return [_account(u) for u in rows], total


def account(db: Any, user_id: int) -> Account | None:
    with db.session() as s:
        u = s.get(User, user_id)
        return _account(u) if u else None


def update_account(db: Any, user_id: int, *, roles: list[str], active: bool, by: int) -> Account:
    """Change an account's roles and whether it is active, never locking the panel out.

    Nobody takes away their own admin role or deactivates themselves, and the
    last active administrator stays one. A deactivated account is signed out
    everywhere.
    """
    roles = sorted({r.strip().lower() for r in roles if r.strip()})
    bad = [r for r in roles if not ROLE.match(r)]
    if bad:
        raise AccountError(f"a role is a short word of letters, digits and dashes, not {bad[0]!r}")
    with db.session() as s, s.begin():
        u = s.get(User, user_id)
        if u is None:
            raise AccountError("no such account")
        was_admin = "admin" in (u.roles or "").split(",") and u.active
        stays_admin = "admin" in roles and active
        if user_id == by and was_admin and not stays_admin:
            raise AccountError(
                "you cannot take away your own administration, or deactivate yourself"
            )
        if was_admin and not stays_admin:
            admins = [
                x
                for x in s.scalars(select(User).where(User.active))
                if "admin" in (x.roles or "").split(",")
            ]
            if len(admins) <= 1:
                raise AccountError("this is the last administrator")
        u.roles = ",".join(roles)
        u.active = bool(active)
        if not active:
            s.execute(delete(Session).where(Session.user_id == user_id))
        return _account(u)


# -- people as an application shows them --
#
# Community modules (messages, the forum, comments) show members and find them by name. An
# application may have its own way of naming them: a game knows its players by their
# characters. It answers two lookups, "people.label" (account id -> the name shown) and
# "people.find" (a name -> account id); then the modules use those, and never show or match an
# email. Without answers, members are shown and found by their account.


def known_as(nest: Any, db: Any, ids: list[int]) -> dict[int, CurrentUser]:
    """Members by id, labelled as the application shows them (people.label), else by account."""
    found = users_by_ids(db, ids)
    if not nest.answered("people.label"):
        return found
    out = {}
    for uid, user in found.items():
        label = nest.lookup("people.label", uid)
        out[uid] = replace(user, name=label or "?", email="")  # the email never shows
    return out


def find_person(nest: Any, db: Any, who: str) -> CurrentUser | None:
    """A member by the name the application knows them by (people.find), else by account."""
    if nest.answered("people.find"):
        uid = nest.lookup("people.find", (who or "").strip())
        return known_as(nest, db, [uid]).get(uid) if uid is not None else None
    return find_user(db, who)
