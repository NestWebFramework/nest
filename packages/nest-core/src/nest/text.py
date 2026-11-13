"""Small text helpers every content module needs."""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

from markupsafe import Markup, escape


def fold(text: str) -> str:
    """Lower case without diacritics: "Știință" → "stiinta"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def slugify(text: str, *, max_length: int = 190, fallback: str = "item") -> str:
    """An address segment: "Biserica din Morlaca" → "biserica-din-morlaca"."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")[:max_length].strip("-") or fallback


_URL = re.compile(r"https?://[^\s<>\"']{1,500}")


def render_plain(text: str, *, link_rel: str = "nofollow ugc noopener") -> Markup:
    """Text someone typed, as safe HTML: escaped, paragraphs, line breaks, web links."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    out = []
    for p in paragraphs:
        parts, pos = [], 0
        for m in _URL.finditer(p):
            url = m.group(0).rstrip(".,;:!?)")
            parts.append(str(escape(p[pos : m.start()])))
            parts.append(f'<a href="{escape(url)}" rel="{link_rel}">{escape(url)}</a>')
            pos = m.start() + len(url)
        parts.append(str(escape(p[pos:])))
        out.append("<p>" + "".join(parts).replace("\n", "<br>") + "</p>")
    return Markup("".join(out))


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("p", "div", "br", "li", "blockquote", "tr"):
            self.parts.append("\n\n" if tag in ("p", "div", "blockquote") else "\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Imported HTML as plain text: tags dropped, entities decoded, paragraphs kept."""
    parser = _Text()
    parser.feed(markup or "")
    parser.close()
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return re.sub(r"\n\s*\n\s*", "\n\n", text).strip()
