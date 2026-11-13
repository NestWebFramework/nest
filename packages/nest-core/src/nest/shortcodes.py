"""Shortcodes: ``[name attr="value"]`` in rich text, answered by whichever module registered it.

The registry belongs to the application, so a gallery module can give the
content module's pages ``[album slug="..."]`` without either importing the
other. A module registers with ``host.shortcode("album", fn)``; a module that
renders rich text calls ``expand(text, request)``. Expansion happens only in
text, never inside a tag, and a shortcode nobody registered stays as written.
A handler returns safe HTML (escape what it inserts); one that fails renders
nothing rather than breaking the page.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable
from typing import Any

from markupsafe import Markup

log = logging.getLogger("nest.shortcodes")

Handler = Callable[[dict[str, str], Any], str]

_SHORTCODE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]{0,60})((?:\s+[^\]]*)?)\]")
_ATTR = re.compile(r"""([a-zA-Z_][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")
_TAG = re.compile(r"(<[^>]*>)")


class ShortcodeError(Exception):
    pass


def attributes(raw: str) -> dict[str, str]:
    raw = html.unescape(raw).replace("”", '"').replace("“", '"').replace("″", '"')
    return {
        m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None)
        for m in _ATTR.finditer(raw)
    }


class Shortcodes:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[str, Handler]] = {}

    def register(self, name: str, owner: str, fn: Handler) -> None:
        key = name.lower()
        if key in self._handlers:
            raise ShortcodeError(f"[{name}] is already answered by {self._handlers[key][0]}")
        self._handlers[key] = (owner, fn)

    def names(self) -> list[str]:
        return sorted(self._handlers)

    def expand(self, text: str, context: Any = None) -> Markup:
        def replace(match: re.Match[str]) -> str:
            found = self._handlers.get(match.group(1).lower())
            if found is None:
                return match.group(0)
            owner, fn = found
            try:
                return str(fn(attributes(match.group(2)), context))
            except Exception:  # noqa: BLE001 - a broken shortcode must not break a page
                log.exception("[%s] of %s failed", match.group(1), owner)
                return ""

        parts = _TAG.split(text or "")
        return Markup(
            "".join(p if p.startswith("<") else _SHORTCODE.sub(replace, p) for p in parts)
        )


def expand(text: str, request: Any, context: Any = None) -> Markup:
    """Expand ``text`` with the shortcodes of the application serving ``request``."""
    return request.app.state.nest.shortcodes.expand(
        text, context if context is not None else request
    )
