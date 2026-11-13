"""Password hashing with the standard library's scrypt: no extra dependency.

A stored hash names its parameters (``scrypt$N$r$p$salt$key``), so they can
be raised later and an old hash still verifies; ``needs_rehash`` says when a
successful sign-in should store a new one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P, KEY_LEN = 2**14, 8, 1, 32
MAX_PASSWORD = 1024  # hashing a megabyte of "password" is a denial of service, not a password


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=length, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> str:
    if len(password) > MAX_PASSWORD:
        raise ValueError("password too long")
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P, KEY_LEN))}"


def verify_password(password: str, stored: str) -> bool:
    if len(password) > MAX_PASSWORD:
        return False
    try:
        algorithm, n, r, p, salt, key = stored.split("$")
        if algorithm != "scrypt":
            return False
        expected = _unb64(key)
        actual = _derive(password, _unb64(salt), int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(f"scrypt${N}${R}${P}$")


# Checked against when the email is unknown, so a wrong email costs as long as
# a wrong password and the timing does not say which accounts exist.
_DUMMY: str | None = None


def dummy_hash() -> str:
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_urlsafe(16))
    return _DUMMY
