"""Pictures in an article shown as the gallery shows its photos.

* A picture the editor emphasized (class ``evidentiat``, the editor's "Emphasize" button):
  framed, full width, its description under it, a magnifier; a tap opens it large in the
  gallery's viewer.
* Emphasized pictures side by side (nothing but space or empty paragraphs between them):
  a mini-gallery, a row of tiles.
* With ``everything`` (the site's "every picture opens large"): every other picture opens
  large too, as it stands.

All the article's pictures that open large are one series in the viewer (its arrows move
between them). A picture that already links to a page (another article) keeps its link.
Without JavaScript each is a link to its large picture.
"""

from __future__ import annotations

import re

SPOT = "evidentiat"
LARGE = 1920
_UNIT = re.compile(r"(?P<open><a\b[^>]*>\s*)?(?P<img><img\b[^>]*>)(?P<close>\s*</a>)?", re.I)
_ATTR = re.compile(r'\b([a-z-]+)="([^"]*)"', re.I)
_PICTURE = re.compile(r"\.(?:jpe?g|png|gif|webp)$", re.I)
_GAP = re.compile(r"^(?:\s|<p>|</p>|<br\s*/?>|&nbsp;)*$", re.I)


def _attrs(tag: str) -> dict[str, str]:
    return {k.lower(): v for k, v in _ATTR.findall(tag)}


def _file(img: dict[str, str]) -> str:
    """The picture's own file on this site (/media/...), from its src or srcset."""
    for candidate in (
        img.get("src", ""),
        img.get("srcset", "").split(",")[0].strip().split(" ")[0],
    ):
        path = candidate.split("?")[0]
        if path.startswith("/media/"):
            return path
    return ""


def transform(html: str, everything: bool = False, viewer: str = "") -> dict:
    """The article's HTML with its pictures shown as the gallery does; ``used``: whether any
    opens in the viewer (then ``viewer``, the viewer's script, is added)."""
    used = False

    def unit(m: re.Match) -> str:
        nonlocal used
        img_tag = m.group("img")
        img = _attrs(img_tag)
        classes = img.get("class", "").split()
        file = _file(img)
        link = _attrs(m.group("open") or "").get("href", "")
        to_page = bool(link) and not (
            link.startswith("/media/") or _PICTURE.search(link.split("?")[0])
        )
        alt = img.get("alt", "") or img.get("title", "")
        large = f"{file}?w={LARGE}" if file else ""
        if SPOT in classes and file:
            caption = f"<figcaption>{alt}</figcaption>" if alt else ""
            if to_page:  # it leads to another page: framed, its link kept
                inner = m.group(0)
            else:
                used = True
                inner = (
                    f'<a href="{large}" class="nest-spot-link" data-lightbox="article"'
                    f' data-caption="{alt}">{img_tag}</a>'
                )
            side = next((c for c in classes if c in ("alignleft", "alignright")), "")
            return (
                f'<figure class="nest-spot{" " + side if side else ""}">{inner}{caption}</figure>'
            )
        if everything and file and not to_page:
            used = True
            return (
                f'<a href="{large}" class="nest-zoom" data-lightbox="article"'
                f' data-caption="{alt}">{img_tag}</a>'
            )
        return m.group(0)

    html = _UNIT.sub(unit, html or "")
    html = _mini_galleries(html)
    if used and viewer:
        html += f'<script src="{viewer}" defer></script>'
    return {"html": html, "used": used}


def _mini_galleries(html: str) -> str:
    """Emphasized pictures side by side, as a row of tiles."""
    spans = [
        (m.start(), m.end())
        for m in re.finditer(r'<figure class="nest-spot">.*?</figure>', html, re.S)
    ]
    if len(spans) < 2:
        return html
    groups, run = [], [spans[0]]
    for prev, cur in zip(spans, spans[1:], strict=False):
        if _GAP.match(html[prev[1] : cur[0]]):
            run.append(cur)
        else:
            groups.append(run)
            run = [cur]
    groups.append(run)
    out, at = [], 0
    for g in groups:
        if len(g) < 2:
            continue
        out.append(html[at : g[0][0]])
        figures = "".join(html[a:b] for a, b in g)
        out.append(f'<div class="nest-spot-grid">{figures}</div>')
        at = g[-1][1]
    out.append(html[at:])
    return "".join(out)
