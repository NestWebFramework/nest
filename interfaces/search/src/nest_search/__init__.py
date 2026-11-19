"""The ``nest.search`` interface.

Documents belong to a ``kind`` (``glossary.term``) and have an id within it.
Search calls are blocking (a provider may reach a database), so a handler that
searches is a plain ``def``, which FastAPI runs in its thread pool.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from markupsafe import Markup, escape

__all__ = ["MARK_END", "MARK_START", "Document", "Hit", "Search", "fold", "highlight", "terms_of"]

# The markers a provider puts around a match in a snippet. They cannot occur in
# text, so highlighting is applied after escaping, never inside markup.
MARK_START, MARK_END = "\x02", "\x03"


@dataclass(frozen=True)
class Document:
    kind: str
    id: str
    title: str
    body: str = ""
    url: str = ""
    # Narrows a search (a dictionary, a category); matched exactly, not searched.
    scope: str = ""


@dataclass(frozen=True)
class Hit:
    kind: str
    id: str
    title: str
    url: str
    scope: str = ""
    snippet: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)

    def snippet_html(self) -> Markup:
        return highlight(self.snippet)


def highlight(text: str) -> Markup:
    """A snippet as safe HTML: everything escaped, the matches in <mark>."""
    return Markup(str(escape(text)).replace(MARK_START, "<mark>").replace(MARK_END, "</mark>"))


def fold(text: str) -> str:
    """Lower case without diacritics: "Știință" → "stiinta"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


_WORD = re.compile(r"\w+", re.UNICODE)


def terms_of(query: str, *, limit: int = 8) -> list[str]:
    """The words of what someone typed; punctuation and operators are not syntax."""
    return _WORD.findall(query)[:limit]


@runtime_checkable
class Search(Protocol):
    def index(self, documents: list[Document]) -> None:
        """Add or replace documents (by kind and id)."""
        ...

    def remove(self, kind: str, ids: list[str]) -> None: ...

    def clear(self, kind: str) -> None:
        """Forget every document of a kind, before indexing it again."""
        ...

    def query(
        self,
        text: str,
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Hit]:
        """Matches for every word typed (the last as a prefix), best first."""
        ...

    def count(self, text: str, *, kind: str | None = None, scope: str | None = None) -> int: ...

    def suggest(
        self, prefix: str, *, kind: str | None = None, scope: str | None = None, limit: int = 8
    ) -> list[Hit]:
        """Titles starting with what was typed so far."""
        ...
