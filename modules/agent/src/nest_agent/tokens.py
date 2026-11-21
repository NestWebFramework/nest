"""The agent's tokens: made at random, the site keeps only their SHA-256.

A token reads ``na_`` and 43 random characters; the site's environment holds
``sha256:<hex>`` of it (``nest agent token APP``), the keeper the token itself.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "na_"


def make() -> tuple[str, str]:
    """A new token and what the site keeps of it: (token, "sha256:…")."""
    token = PREFIX + secrets.token_urlsafe(32)
    return token, kept(token)


def kept(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def _matches(token: str, setting: str) -> bool:
    setting = setting.strip()
    if not setting.startswith("sha256:") or len(setting) != 71:
        return False  # never a token in clear in the settings, never an empty one
    return hmac.compare_digest(kept(token), setting.lower())


def scope_of(token: str, *, read: str, control: str) -> str | None:
    """ "control", "read" or None: which of the site's tokens this one is."""
    if not token.startswith(PREFIX) or len(token) > 100:
        return None
    if control and _matches(token, control):
        return "control"
    if read and _matches(token, read):
        return "read"
    return None
