"""Small text helpers every content module needs."""

from __future__ import annotations

import re
import unicodedata


def fold(text: str) -> str:
    """Lower case without diacritics: "Știință" → "stiinta"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def slugify(text: str, *, max_length: int = 190, fallback: str = "item") -> str:
    """An address segment: "Biserica din Morlaca" → "biserica-din-morlaca"."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")[:max_length].strip("-") or fallback
