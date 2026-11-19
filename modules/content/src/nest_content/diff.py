"""What changed between two versions of an entry, for an editor's eyes.

The text is compared as a reader sees it: the HTML reduced to its blocks (paragraphs,
headings, list items, cells) and each block's words, so a changed word shows as that
word struck out and its replacement, not as a rewritten line of markup. A long run of
unchanged blocks folds to its first and last. Everything is escaped: a version's text
is shown, never run.
"""

from __future__ import annotations

import difflib
import html
import re
from collections.abc import Callable
from typing import Any

from markupsafe import Markup, escape

_BREAK = re.compile(
    r"</(?:p|h[1-6]|li|td|th|blockquote|figcaption|pre|div|tr)>|<br\s*/?>|<hr\s*/?>|<img\b[^>]*>",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")
_ALT = re.compile(r'alt="([^"]*)"', re.I)
_SAME = '<p class="diff-same">'


def blocks(markup: str, picture: str = "picture") -> list[str]:
    """The text of each block, in order (a picture as [picture: its description])."""

    def mark(m: re.Match[str]) -> str:
        tag = m.group(0)
        if tag.lower().startswith("<img"):
            alt = _ALT.search(tag)
            said = html.unescape(alt.group(1)).strip() if alt else ""
            return f"\n[{picture}{': ' + said if said else ''}]\n"
        return "\n"

    text = _BREAK.sub(mark, markup or "")
    text = html.unescape(_TAG.sub("", text))
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def _words(a: str, b: str) -> str:
    wa, wb = a.split(" "), b.split(" ")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape(" ".join(wa[i1:i2])))
            continue
        if i2 > i1:
            out.append(f"<del>{escape(' '.join(wa[i1:i2]))}</del>")
        if j2 > j1:
            out.append(f"<ins>{escape(' '.join(wb[j1:j2]))}</ins>")
    return " ".join(out)


def text_diff(
    old: str,
    new: str,
    *,
    picture: str = "picture",
    unchanged: Callable[[int], str] | None = None,
) -> tuple[Markup, int]:
    """``old`` → ``new`` as blocks with the changed words marked; and how many blocks changed.
    With ``unchanged``, a run of more than three unchanged blocks folds to its first and
    last, ``unchanged(n)`` saying how many are between."""
    a, b = blocks(old, picture), blocks(new, picture)
    rows, changed = [], 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            rows += [f"{_SAME}{escape(x)}</p>" for x in a[i1:i2]]
        elif op == "replace" and (i2 - i1) == (j2 - j1):
            changed += i2 - i1
            pairs = zip(a[i1:i2], b[j1:j2], strict=True)
            rows += [f'<p class="diff-changed">{_words(x, y)}</p>' for x, y in pairs]
        else:
            changed += max(i2 - i1, j2 - j1)
            rows += [f'<p class="diff-removed"><del>{escape(x)}</del></p>' for x in a[i1:i2]]
            rows += [f'<p class="diff-added"><ins>{escape(y)}</ins></p>' for y in b[j1:j2]]
    if unchanged is not None:
        rows = _fold(rows, unchanged)
    return Markup("\n".join(rows)), changed


def _fold(rows: list[str], unchanged: Callable[[int], str]) -> list[str]:
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if len(run) > 3:
            note = escape(unchanged(len(run) - 2))
            out.extend([run[0], f'<p class="diff-fold">… {note} …</p>', run[-1]])
        else:
            out.extend(run)
        run.clear()

    for row in rows:
        if row.startswith(_SAME):
            run.append(row)
        else:
            flush()
            out.append(row)
    flush()
    return out


def field_changes(
    old: dict[str, Any], new: dict[str, Any], labels: dict[str, str]
) -> list[tuple[str, str, str]]:
    """[(label, then, now)] for each field that differs (the text is compared apart)."""
    out = []
    for key, label in labels.items():
        a, b = old.get(key), new.get(key)
        if (a or None) != (b or None):
            out.append((label, _show(a), _show(b)))
    return out


def _show(value: Any) -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items() if v not in (None, ""))
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)
