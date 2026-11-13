"""HTML bodies: sanitized when they are stored, shortcodes expanded when shown.

A body is HTML, because WordPress's and Geticus's are, so it is cleaned with
an allow-list (nh3, the Rust ammonia sanitizer) every time it is saved: no
script, no event handler, no style attribute, links only to http(s), mailto
and this site. Shortcodes such as ``[catlist id=3]`` stay in the stored text
and are expanded when the page is shown; one nobody registered stays as it
was written, as WordPress does.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

import nh3
from markupsafe import Markup, escape

TAGS = {
    "p",
    "br",
    "hr",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "sub",
    "sup",
    "small",
    "mark",
    "blockquote",
    "q",
    "cite",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "a",
    "img",
    "figure",
    "figcaption",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "pre",
    "code",
    "span",
    "div",
    "abbr",
    "time",
}
ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "abbr": {"title"},
    "time": {"datetime"},
    "ol": {"start", "reversed"},
    "*": {"class", "id", "lang"},
}


def sanitize(markup: str) -> str:
    """HTML reduced to what a page body may hold."""
    cleaned = nh3.clean(
        markup or "",
        tags=TAGS,
        attributes=ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener",
        strip_comments=True,
    )
    return _EMPTY_P.sub("", cleaned)


# A paragraph holding nothing but spaces and breaks: WordPress left many.
_EMPTY_P = re.compile(r"<p>(?:\s|&nbsp;|\xa0|<br\s*/?>)*</p>\s*")


_BLOCK = r"(?:table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|pre|form|map|area|blockquote|address|math|style|p|h[1-6]|hr|fieldset|legend|section|article|aside|hgroup|header|footer|nav|figure|figcaption|details|menu|summary)"


def autop(text: str) -> str:
    """WordPress's wpautop, in short: blank lines are paragraphs, single newlines breaks.

    WordPress stores posts without <p>; it adds them when a post is shown. An
    imported post gets them once, here, so it is stored as the page shows it.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = re.sub(rf"(<{_BLOCK}[^>]*>)", r"\n\n\1", text)
    text = re.sub(rf"(</{_BLOCK}>)", r"\1\n\n", text)
    out = []
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.match(rf"^</?{_BLOCK}[\s/>]", chunk):
            out.append(chunk)
        else:
            out.append("<p>" + chunk.replace("\n", "<br>\n") + "</p>")
    return re.sub(r"<p>\s*(?:<br>\s*)*</p>\n?", "", "\n".join(out))


# --- shortcodes --------------------------------------------------------------------

Shortcode = Callable[[dict[str, str], Any], str]
SHORTCODES: dict[str, Shortcode] = {}
_SHORTCODE = re.compile(r"\[([a-z][a-z0-9_-]{0,40})((?:\s+[^\]]*)?)\]")
_ATTR = re.compile(r"""([a-zA-Z_][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")


def shortcode(name: str) -> Callable[[Shortcode], Shortcode]:
    """Register a shortcode: a function of its attributes and a context, returning safe HTML."""

    def register(fn: Shortcode) -> Shortcode:
        SHORTCODES[name] = fn
        return fn

    return register


def attributes(raw: str) -> dict[str, str]:
    raw = html.unescape(raw)
    return {
        m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None)
        for m in _ATTR.finditer(raw)
    }


def expand(body: str, context: Any) -> Markup:
    """The stored (already clean) body with registered shortcodes replaced."""

    def replace(match: re.Match[str]) -> str:
        fn = SHORTCODES.get(match.group(1))
        if fn is None:
            return match.group(0)
        try:
            return str(fn(attributes(match.group(2)), context))
        except Exception:  # noqa: BLE001 - a broken shortcode must not break a page
            return ""

    # Only in text: a shortcode written inside a tag's attribute stays as it is.
    parts = _TAG.split(body or "")
    return Markup(
        "".join(part if part.startswith("<") else _SHORTCODE.sub(replace, part) for part in parts)
    )


_TAG = re.compile(r"(<[^>]*>)")


def link_list(items: list[tuple[str, str]]) -> str:
    """A list of links, escaped: what most shortcodes answer."""
    if not items:
        return ""
    lis = "".join(f'<li><a href="{escape(url)}">{escape(title)}</a></li>' for title, url in items)
    return f'<ul class="shortcode-list">{lis}</ul>'
