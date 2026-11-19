"""HTML bodies: sanitized when they are stored, shortcodes expanded when shown.

A body is HTML, because WordPress's and Geticus's are, so it is cleaned with
an allow-list (nh3, the Rust ammonia sanitizer) every time it is saved: no
script, no event handler, no style attribute, links only to http(s), mailto
and this site. Shortcodes such as ``[catlist id=3]`` stay in the stored text
and are expanded when the page is shown, by the application's shortcode
registry (nest.shortcodes); one nobody registered stays as written.
"""

from __future__ import annotations

import re

import nh3
from markupsafe import escape

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


# --- for shortcode handlers ------------------------------------------------------


def link_list(items: list[tuple[str, str]]) -> str:
    """A list of links, escaped: what most shortcodes answer."""
    if not items:
        return ""
    lis = "".join(f'<li><a href="{escape(url)}">{escape(title)}</a></li>' for title, url in items)
    return f'<ul class="shortcode-list">{lis}</ul>'


# --- videos ----------------------------------------------------------------------

# A YouTube address alone in a paragraph (how WordPress embedded one, by oEmbed), bare
# or as a link to itself, with the stray spaces WordPress's editor left around it.
_YOUTUBE_ID = r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})"
_ALONE = re.compile(
    rf"<(p|div)>\s*(?:<a [^>]*>\s*)?{_YOUTUBE_ID}[^\s<]*\s*(?:</a>)?"
    r"(?:\s|&nbsp;|\xa0|<br\s*/?>|<span>(?:\s|&nbsp;|\xa0)*</span>)*</\1>"
)
_ID = re.compile(rf"^{_YOUTUBE_ID}|^([\w-]{{11}})$")


def youtube_id(value: str) -> str | None:
    """The video's id in a YouTube address (or an id given as it is), or None."""
    m = _ID.match((value or "").strip())
    return (m.group(1) or m.group(2)) if m else None


def video(video_id: str, label: str) -> str:
    """A video that loads only when it is played: until then a link, so a page asks
    nothing of YouTube (no cookie, no request) for a reader who does not play it.
    The content module's video.js turns the link into the player (youtube-nocookie)."""
    vid = escape(video_id)
    return (
        f'<figure class="video" data-video="{vid}">'
        f'<a class="video-play" href="https://www.youtube.com/watch?v={vid}" rel="noopener">'
        f"<span>{escape(label)}</span></a></figure>"
    )


def embed_videos(markup: str, label: str) -> str:
    """Each YouTube address standing alone in a paragraph, as a video."""
    return _ALONE.sub(lambda m: video(m.group(2), label), markup or "")
