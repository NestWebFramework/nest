"""Accounts kept by their devices, their key and (later) their passkeys and PIN.

The account's key is a 20-character code (about 98 bits) shown once, as a link and as text;
the database keeps its SHA-256. Using it signs a browser in, on any device, until the player
makes a new one. Adding a device from a signed-in one gives a link and 6 digits for ten
minutes, single use. Accounts never protected (no key saved, no passkey, no PIN) go after
`unprotected_days` without play, every account after `inactive_days`; the modules holding
their data hear `account.forget` first.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from nest_auth import (
    CurrentUser,
    active_user,
    close_session_id,
    create_keyless,
    keyless_accounts,
    remove_account,
    sessions_of,
)
from sqlalchemy import delete, select

from nest_keys.models import AccountKey, Pairing, utcnow

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read aloud, typed from paper
CODE_LENGTH = 20
PAIRING_MINUTES = 10
PAIRING_TRIES = 5


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4))


def clean(code: str) -> str:
    """A code as typed or pasted: spaces, dashes and capitals do not matter."""
    plain = "".join(c for c in (code or "").lower() if c.isalnum())
    plain = plain.replace("0", "o").replace("1", "l")  # a hand that wrote them anyway
    return "-".join(plain[i : i + 4] for i in range(0, len(plain), 4))


# --- the account and its key ---------------------------------------------------------


def start(db: Any, name: str = "") -> tuple[CurrentUser, str]:
    """A new account (no email, no password) and its key's code, to show once."""
    user = create_keyless(db, name)
    return user, new_key(db, user.id)


def new_key(db: Any, user_id: int) -> str:
    """A new key for the account; the old one stops working. The code, to show once."""
    code = new_code()
    with db.session() as s, s.begin():
        s.execute(delete(AccountKey).where(AccountKey.user_id == user_id))
        s.add(AccountKey(id=digest(clean(code)), user_id=user_id, created_at=utcnow(), saved=0))
    return code


def mark_saved(db: Any, user_id: int) -> None:
    with db.session() as s, s.begin():
        key = s.scalar(select(AccountKey).where(AccountKey.user_id == user_id))
        if key is not None:
            key.saved = 1


def key_of(db: Any, user_id: int) -> AccountKey | None:
    with db.session() as s:
        return s.scalar(select(AccountKey).where(AccountKey.user_id == user_id))


def by_key(db: Any, code: str) -> CurrentUser | None:
    """The account whose key this is (an active one), else None."""
    plain = clean(code)
    if len(plain.replace("-", "")) != CODE_LENGTH:
        return None
    with db.session() as s, s.begin():
        key = s.get(AccountKey, digest(plain))
        user = active_user(db, key.user_id) if key else None
        if key is None or user is None:
            return None
        key.used_at = utcnow()
        key.saved = 1  # it was kept somewhere: it is saved
        return user


# --- adding a device -----------------------------------------------------------------


def pair_start(db: Any, user_id: int) -> tuple[str, str]:
    """A link's token and 6 digits that sign in another device, for ten minutes, once."""
    now = utcnow()
    token = secrets.token_urlsafe(24)
    with db.session() as s, s.begin():
        s.execute(delete(Pairing).where((Pairing.user_id == user_id) | (Pairing.expires_at < now)))
        busy = set(s.scalars(select(Pairing.code)))
        digits = f"{secrets.randbelow(10**6):06d}"
        while digest(digits) in busy:  # unique among the codes alive now
            digits = f"{secrets.randbelow(10**6):06d}"
        s.add(
            Pairing(
                user_id=user_id,
                link=digest(token),
                code=digest(digits),
                expires_at=now + timedelta(minutes=PAIRING_MINUTES),
                tries=0,
            )
        )
    return token, digits


def pair_use(db: Any, *, token: str = "", digits: str = "") -> CurrentUser | None:
    """The account a pairing's link or digits belong to (and the pairing is spent)."""
    now = utcnow()
    digits = "".join(c for c in digits if c.isdigit())
    if not token and len(digits) != 6:
        return None
    with db.session() as s, s.begin():
        column, value = (Pairing.link, digest(token)) if token else (Pairing.code, digest(digits))
        pairing = s.scalar(select(Pairing).where(column == value, Pairing.expires_at > now))
        if pairing is None or pairing.tries >= PAIRING_TRIES:
            return None
        user_id = pairing.user_id
        s.delete(pairing)
    return active_user(db, user_id)


# --- devices -------------------------------------------------------------------------


@dataclass
class Device:
    id: str  # the session's id (a SHA-256)
    name: str
    created_at: datetime
    last_seen_at: datetime
    this: bool


def device_name(user_agent: str) -> str:
    """A browser as a person names it: "Chrome pe Android", "Safari pe iPhone"."""
    ua = user_agent or ""
    system = next(
        (
            n
            for k, n in (
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("Windows", "Windows"),
                ("Mac OS", "Mac"),
                ("CrOS", "Chromebook"),
                ("Linux", "Linux"),
            )
            if k in ua
        ),
        "",
    )
    browser = next(
        (
            n
            for k, n in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("Firefox/", "Firefox"),
                ("CriOS", "Chrome"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if k in ua
        ),
        "",
    )
    return " · ".join(x for x in (browser, system) if x) or "?"


def devices(db: Any, user_id: int, this_session: str = "") -> list[Device]:
    return [
        Device(r.id, device_name(r.user_agent), r.created_at, r.last_seen_at, r.id == this_session)
        for r in sessions_of(db, user_id)
    ]


def sign_out_device(db: Any, user_id: int, session_id: str) -> None:
    close_session_id(db, user_id, session_id)


# --- accounts that go ----------------------------------------------------------------


def protected(db: Any, user_id: int) -> bool:
    """Whether the account can come back without this browser: its key saved, or a passkey."""
    from nest_keys.passkeys import of

    key = key_of(db, user_id)
    return bool(key and key.saved) or bool(of(db, user_id))


def cleanup(
    db: Any,
    forget: Any,
    *,
    unprotected_days: int = 14,
    inactive_days: int = 365,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Remove the keyless accounts unused too long: (unprotected removed, inactive removed).
    ``forget(user_id)`` tells the modules holding their data first."""
    now = now or utcnow()
    from nest_keys.models import Challenge, DevicePin, Passkey
    from nest_keys.passkeys import users_with

    with db.session() as s:
        saved = set(s.scalars(select(AccountKey.user_id).where(AccountKey.saved == 1)))
        used = dict(s.execute(select(AccountKey.user_id, AccountKey.used_at)).all())
    saved |= users_with(db)
    gone_unprotected = gone_inactive = 0
    for uid, created, last in keyless_accounts(db):
        seen = max(x for x in (created, last, used.get(uid)) if x is not None)
        idle = now - seen
        if idle > timedelta(days=inactive_days):
            gone_inactive += 1
        elif uid not in saved and idle > timedelta(days=unprotected_days):
            gone_unprotected += 1
        else:
            continue
        forget(uid)
        with db.session() as s, s.begin():
            s.execute(delete(AccountKey).where(AccountKey.user_id == uid))
            s.execute(delete(Pairing).where(Pairing.user_id == uid))
            s.execute(delete(Passkey).where(Passkey.user_id == uid))
            s.execute(delete(DevicePin).where(DevicePin.user_id == uid))
            s.execute(delete(Challenge).where(Challenge.user_id == uid))
        remove_account(db, uid)
    return gone_unprotected, gone_inactive


def discard(db: Any, user_id: int) -> None:
    """An account just made and not wanted after all (its character refused): gone, with
    everything of it here."""
    from nest_keys.models import Challenge, DevicePin, Passkey

    with db.session() as s, s.begin():
        for model in (AccountKey, Pairing, Passkey, DevicePin, Challenge):
            s.execute(delete(model).where(model.user_id == user_id))
    remove_account(db, user_id)
