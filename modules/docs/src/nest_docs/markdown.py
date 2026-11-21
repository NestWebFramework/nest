"""Markdown for documentation pages, written by the project's own authors: a careful
subset of CommonMark and GitHub's tables, rendered to safe HTML.

Blocks: front matter (YAML between ``---`` lines), headings (``#`` .. ``######``, each with
an anchor), paragraphs, fenced code (```` ```lang ````, highlighted by Pygments), lists
(``-``, ``*``, ``1.``; nested by indentation), block quotes (with GitHub's ``> [!NOTE]``
call-outs), tables, rules. Inline: ``code``, **strong**, *emphasis*, [links](url),
![images](src "title"), <https://autolinks>, line breaks (two spaces). Raw HTML is never
passed through: what the text says is escaped.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from markupsafe import Markup

_FENCE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w+#.-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CALLOUT = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", re.I)


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


@dataclass
class Page:
    """A rendered page: its front matter, its HTML, its headings (for the contents
    beside it), its title and its plain text (for the search index)."""

    meta: dict[str, Any]
    html: Markup
    headings: list[Heading] = field(default_factory=list)
    text: str = ""

    @property
    def title(self) -> str:
        if self.meta.get("title"):
            return str(self.meta["title"])
        first = next((h for h in self.headings if h.level == 1), None)
        return first.text if first else ""


def slug(text: str) -> str:
    """An anchor from a heading, as GitHub makes them (lowercase, dashes, letters kept)."""
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", text)


def front_matter(source: str) -> tuple[dict[str, Any], str]:
    if source.startswith("---\n"):
        end = source.find("\n---", 4)
        if end > 0:
            try:
                meta = yaml.safe_load(source[4:end]) or {}
            except yaml.YAMLError:
                meta = {}
            rest = source[end + 4 :]
            return (meta if isinstance(meta, dict) else {}), rest.lstrip("\n")
    return {}, source


# --- inline ---------------------------------------------------------------------------

_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
_IMAGE = re.compile(r'!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+"([^"]*)")?\s*\)')
_LINK = re.compile(r'\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+"([^"]*)")?\s*\)')
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_EM = re.compile(r"(?<![\w*])(\*|_)(?=\S)(.+?)(?<=\S)\1(?![\w*])", re.S)


def _safe_url(url: str) -> str:
    u = url.strip()
    if re.match(r"^(https?:|mailto:|/|#|\.|[\w./-]+$)", u) and not u.lower().startswith(
        "javascript:"
    ):
        return u
    return "#"


def inline(text: str, link: Any = None) -> str:
    """One run of inline Markdown as HTML. ``link`` may rewrite a link or an image's
    address (a page's relative link made the site's)."""
    link = link or (lambda url, image=False: url)
    slots: list[str] = []

    def keep(fragment: str) -> str:
        slots.append(fragment)
        return f"\x00{len(slots) - 1}\x00"

    text = _CODE_SPAN.sub(lambda m: keep(f"<code>{html.escape(m.group(2).strip())}</code>"), text)
    text = _AUTOLINK.sub(
        lambda m: keep(
            f'<a href="{html.escape(_safe_url(m.group(1)))}">{html.escape(m.group(1))}</a>'
        ),
        text,
    )

    def image(m: re.Match) -> str:
        alt, src, title = m.group(1), link(m.group(2), True), m.group(3)
        t = f' title="{html.escape(title)}"' if title else ""
        return keep(
            f'<img src="{html.escape(_safe_url(src))}" alt="{html.escape(alt)}"{t} loading="lazy">'
        )

    text = _IMAGE.sub(image, text)

    def anchor(m: re.Match) -> str:
        label, url, title = m.group(1), link(m.group(2)), m.group(3)
        t = f' title="{html.escape(title)}"' if title else ""
        outside = url.startswith(("http://", "https://"))
        rel = ' rel="noopener"' if outside else ""
        return keep(
            f'<a href="{html.escape(_safe_url(url))}"{t}{rel}>{_emphasis(html.escape(label))}</a>'
        )

    text = _LINK.sub(anchor, text)
    text = html.escape(text, quote=False)
    text = _emphasis(text)
    text = re.sub(r"  \n", "<br>\n", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)


def _emphasis(text: str) -> str:
    text = _STRONG.sub(r"<strong>\2</strong>", text)
    return _EM.sub(r"<em>\2</em>", text)


def _plain(text: str) -> str:
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    return re.sub(r"[`*_]", "", text)


# --- code -----------------------------------------------------------------------------


def highlight(code: str, lang: str) -> str:
    """Code with Pygments' classes (``.hl`` and its tokens); plain when the language is
    not one Pygments knows."""
    try:
        from pygments import highlight as pyg
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name

        lexer = get_lexer_by_name({"sh": "bash", "shell": "bash", "yml": "yaml"}.get(lang, lang))
        return pyg(code, lexer, HtmlFormatter(nowrap=True))
    except Exception:  # an unknown language, or no Pygments: the code as it is
        return html.escape(code)


# --- blocks ---------------------------------------------------------------------------


def render(source: str, link: Any = None) -> Page:
    meta, body = front_matter(source.replace("\r\n", "\n"))
    lines = body.split("\n")
    out: list[str] = []
    headings: list[Heading] = []
    words: list[str] = []
    used: dict[str, int] = {}
    _blocks(lines, out, headings, words, used, link)
    return Page(meta, Markup("\n".join(out)), headings, " ".join(words))


def _blocks(lines, out, headings, words, used, link) -> None:  # noqa: C901 - one pass, many kinds
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            text = "\n".join(s.strip() for s in para)
            out.append(f"<p>{inline(text, link)}</p>")
            words.append(_plain(text))
            para.clear()

    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            flush()
            mark, lang = fence.group(2), fence.group(3)
            body = []
            i += 1
            while i < n and not lines[i].strip().startswith(mark[0] * len(mark)):
                body.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(body)
            label = f' data-lang="{html.escape(lang)}"' if lang else ""
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(
                f'<pre class="hl"{label}><code{cls}>{highlight(code, lang) if lang else html.escape(code)}</code></pre>'
            )
            words.append(code)
            continue
        head = _HEADING.match(line)
        if head:
            flush()
            level, text = len(head.group(1)), head.group(2)
            base = slug(_plain(text)) or "section"
            used[base] = used.get(base, 0) + 1
            anchor = base if used[base] == 1 else f"{base}-{used[base] - 1}"
            headings.append(Heading(level, _plain(text), anchor))
            out.append(
                f'<h{level} id="{anchor}">{inline(text, link)}'
                f'<a class="anchor" href="#{anchor}" aria-hidden="true">#</a></h{level}>'
            )
            words.append(_plain(text))
            i += 1
            continue
        if _RULE.match(line) and not para:
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith(">"):
            flush()
            quoted = []
            while i < n and lines[i].lstrip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            kind = _CALLOUT.match(quoted[0]) if quoted else None
            inner: list[str] = []
            _blocks(quoted[1:] if kind else quoted, inner, headings, words, used, link)
            if kind:
                k = kind.group(1).lower()
                out.append(
                    f'<aside class="callout callout-{k}" role="note"><p class="callout-title">{k.capitalize()}</p>{"".join(inner)}</aside>'
                )
            else:
                out.append(f"<blockquote>{''.join(inner)}</blockquote>")
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush()
            out.append(_table(lines, i, link))
            words.append(_plain(line))
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                words.append(_plain(lines[i]))
                i += 1
            continue
        item = _ITEM.match(line)
        # a list may follow a line of text straight away (a bullet, or a numbered list
        # that starts at 1), as in CommonMark
        if item and (not para or not item.group(2)[0].isdigit() or item.group(2)[:1] == "1"):
            flush()
            i = _list(lines, i, out, headings, words, used, link)
            continue
        para.append(line)
        i += 1
    flush()


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


def _table(lines: list[str], i: int, link: Any) -> str:
    head = _cells(lines[i])
    aligns = []
    for c in _cells(lines[i + 1]):
        aligns.append(
            "center"
            if c.startswith(":") and c.endswith(":")
            else "right"
            if c.endswith(":")
            else ""
        )
    rows = []
    j = i + 2
    while j < len(lines) and "|" in lines[j] and lines[j].strip():
        rows.append(_cells(lines[j]))
        j += 1

    def cell(tag: str, text: str, k: int) -> str:
        a = aligns[k] if k < len(aligns) and aligns[k] else ""
        style = f' class="align-{a}"' if a else ""
        return f"<{tag}{style}>{inline(text, link)}</{tag}>"

    thead = "".join(cell("th", c, k) for k, c in enumerate(head))
    body = "".join(
        "<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>" for r in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table></div>'


def _list(lines, i, out, headings, words, used, link) -> int:
    first = _ITEM.match(lines[i])
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    start = int(re.match(r"\d+", first.group(2)).group()) if ordered else 1
    items: list[list[str]] = []
    n = len(lines)
    while i < n:
        m = _ITEM.match(lines[i])
        if m and len(m.group(1)) == indent and m.group(2)[0].isdigit() == ordered:
            items.append([m.group(3)])
            i += 1
            continue
        line = lines[i]
        if not line.strip():
            nxt = next((lines[j] for j in range(i + 1, n) if lines[j].strip()), "")
            nm = _ITEM.match(nxt)
            deeper = len(nxt) - len(nxt.lstrip()) > indent
            if nxt and (deeper or (nm and len(nm.group(1)) == indent)):
                items[-1].append("")
                i += 1
                continue
            break
        if len(line) - len(line.lstrip()) > indent:
            items[-1].append(
                line[indent + 2 :] if line[: indent + 2].strip() == "" else line.strip()
            )
            i += 1
            continue
        break
    tag = "ol" if ordered else "ul"
    attr = f' start="{start}"' if ordered and start != 1 else ""
    parts = []
    for item in items:
        inner: list[str] = []
        loose = "" in item[:-1]
        _blocks(item, inner, headings, words, used, link)
        html_ = "".join(inner)
        if not loose and html_.startswith("<p>"):  # a tight item: no paragraph around its text
            html_ = re.sub(r"^<p>(.*?)</p>", r"\1", html_, count=1, flags=re.S)
        parts.append(f"<li>{html_}</li>")
    out.append(f"<{tag}{attr}>{''.join(parts)}</{tag}>")
    return i


def stylesheet() -> str:
    """Pygments' colours for the code (light and dark), as the docs' CSS appends them."""
    try:
        from pygments.formatters import HtmlFormatter

        light = HtmlFormatter(style="friendly").get_style_defs(".hl")
        dark = HtmlFormatter(style="monokai").get_style_defs(".hl")
        return f"{light}\n@media (prefers-color-scheme: dark) {{\n{dark}\n}}\n"
    except Exception:
        return ""
