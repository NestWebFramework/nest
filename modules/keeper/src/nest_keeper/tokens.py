"""The API's tokens: made at random, shown once, kept as SHA-256 hashes, revocable."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from nest_keeper.models import KeeperToken, utcnow

PREFIX = "nk_"
SCOPES = ("read",)
USED_EVERY = timedelta(minutes=1)  # last use written at most this often


@dataclass
class Token:
    id: int
    name: str
    prefix: str
    scopes: tuple[str, ...]
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token(t: KeeperToken) -> Token:
    return Token(
        t.id,
        t.name,
        t.prefix,
        tuple(x for x in t.scopes.split(",") if x),
        t.created_at,
        t.last_used_at,
        t.revoked,
    )


def create(db: Any, name: str, scopes: tuple[str, ...] = ("read",)) -> tuple[str, Token]:
    """A new token: the secret (to show once, never stored) and what is kept of it."""
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("a token needs a name, of at most 120 characters")
    bad = [s for s in scopes if s not in SCOPES]
    if bad:
        raise ValueError(f"no scope {bad[0]!r} (scopes: {', '.join(SCOPES)})")
    secret = PREFIX + secrets.token_urlsafe(32)
    with db.session() as s, s.begin():
        row = KeeperToken(
            name=name, prefix=secret[:10], digest=digest(secret), scopes=",".join(scopes)
        )
        s.add(row)
        s.flush()
        return secret, _token(row)


def check(db: Any, secret: str) -> Token | None:
    """The live token this secret is, or None. Compared by hash, in constant time."""
    if not secret.startswith(PREFIX) or len(secret) > 100:
        return None
    wanted = digest(secret)
    with db.session() as s:
        row = s.scalar(select(KeeperToken).where(KeeperToken.digest == wanted))
        if row is None or row.revoked or not hmac.compare_digest(row.digest, wanted):
            return None
        found = _token(row)
    now = utcnow()
    if found.last_used_at is None or now - found.last_used_at > USED_EVERY:
        with db.session() as s, s.begin():
            s.execute(
                update(KeeperToken).where(KeeperToken.id == found.id).values(last_used_at=now)
            )
    return found


def listing(db: Any) -> list[Token]:
    with db.session() as s:
        return [_token(t) for t in s.scalars(select(KeeperToken).order_by(KeeperToken.id.desc()))]


def revoke(db: Any, token_id: int) -> bool:
    with db.session() as s, s.begin():
        row = s.get(KeeperToken, token_id)
        if row is None:
            return False
        row.revoked = True
        return True
