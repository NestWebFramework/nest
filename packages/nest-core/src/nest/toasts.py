"""Toasts: a short message for the person who just did something ("Saved.").

A module says it with ``toast(request, _("Saved."))``, whatever it answers next: a page,
a redirect, an htmx fragment. The notifications module, when the application includes
it, carries the message there (a signed cookie read once by the next page, or an htmx
header shown at once); without it, a toast is quietly dropped, so a module can always
call this.
"""

from __future__ import annotations

from typing import Any, Literal

Level = Literal["success", "info", "warning", "error"]
LEVELS = ("success", "info", "warning", "error")
MAX_TEXT = 300


def toast(request: Any, text: str, level: Level = "success") -> None:
    """Tell the person who made this request ``text`` (already in their language)."""
    if level not in LEVELS:
        level = "info"
    text = " ".join(str(text).split())[:MAX_TEXT]
    if text:
        outgoing = getattr(request.state, "toasts_out", None)
        if outgoing is None:  # kept in the request's scope, where the notifications module looks
            outgoing = request.state.toasts_out = []
        if len(outgoing) < 5:
            outgoing.append({"text": text, "level": level})
