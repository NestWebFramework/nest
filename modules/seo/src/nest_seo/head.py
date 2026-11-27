"""The head of a page, as search engines and shared links read it.

``head(request, subject, title=..., ...)`` writes the description, keywords, robots,
canonical, Open Graph, Twitter card and structured data (JSON-LD) of a page: what the
editors said about it (its subject's row) first, then what the module knows (its title,
its excerpt, its picture), then the site's defaults (the module's settings). Every value
is escaped; the JSON-LD cannot close its script element.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from markupsafe import Markup, escape

from nest import translator
from nest.host import module_state
from nest_seo import service


def _settings(request: Any) -> Any:
    return module_state(request, "seo")["settings"]


def site_url(request: Any) -> str:
    configured = str(_settings(request).get("site_url") or "")
    return (configured or str(request.base_url)).rstrip("/")


def absolute(request: Any, path: str) -> str:
    if not path or path.startswith(("https://", "http://")):
        return path
    return site_url(request) + (path if path.startswith("/") else "/" + path)


def picture(request: Any, key: str, width: int | None = 1280) -> str:
    """A stored picture's (or an https picture's) absolute address."""
    if not key:
        return ""
    if key.startswith("https://"):
        return key
    base = request.app.state.nest.lookup("media.base", None)
    base = "/media" if base is None else base
    return absolute(request, f"{base}/{quote(key)}" + (f"?w={width}" if width else ""))


def _meta(request: Any, subject: str) -> Any:
    cache = request.scope.setdefault("state", {}).setdefault("seo_meta", {})
    if subject not in cache:
        db = request.app.state.nest.bindings.get("nest.db")
        cache[subject] = service.get(db, subject) if subject else None
    return cache[subject]


def _translated(request: Any) -> str:
    """The language of a page that is in another language than the default (its own
    text, not the original's standing in for it), else ""."""
    state = request.scope.get("state", {})
    locale = str(state.get("locale") or "")
    default = request.app.state.nest.catalogs.default
    if not locale or locale == default or state.get("language_fallback"):
        return ""
    return locale


def _words(request: Any, subject: str) -> Any:
    """What editors said of a page in words (title, description, keywords), in the page's
    language: the default's row, or, on a translated page, that language's (None when it
    has none: the page's own translated text is better than the original's words)."""
    locale = _translated(request)
    if not locale:
        return _meta(request, subject)
    cache = request.scope.setdefault("state", {}).setdefault("seo_text", {})
    if subject not in cache:
        db = request.app.state.nest.bindings.get("nest.db")
        cache[subject] = service.text(db, subject, locale) if subject else None
    return cache[subject]


def title(request: Any, subject: str, default: str) -> str:
    """A page's title in search results and the browser tab, as the site writes them."""
    m = _words(request, subject)
    own = (m.title if m and m.title else default) or ""
    site = request.app.state.nest.title
    if not own or own == site:
        return site
    pattern = str(_settings(request).get("title_pattern") or "{title}")
    try:
        return pattern.format(title=own, site=site)
    except (KeyError, IndexError, ValueError):
        return f"{own} · {site}"


def _ld(data: dict[str, Any]) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{text}</script>'


# a language as Open Graph names a locale: its language and its country
OG_LOCALES = {
    "ro": "ro_RO",
    "en": "en_US",
    "hu": "hu_HU",
    "de": "de_DE",
    "fr": "fr_FR",
    "it": "it_IT",
    "es": "es_ES",
}


def og_locale(locale: str) -> str:
    locale = locale.replace("-", "_")
    return locale if "_" in locale else OG_LOCALES.get(locale, locale)


def _trail(request: Any, site: str, crumbs: list[tuple[str, str]]) -> dict[str, Any]:
    """The way to a page from the home page (BreadcrumbList): search results may show it."""
    steps = [(site, "/"), *[(n, p) for n, p in crumbs if n and p and p != "/"]]
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": absolute(request, path)}
            for i, (name, path) in enumerate(steps, 1)
        ],
    }


def _iso(when: Any) -> str:
    return when.isoformat() if isinstance(when, datetime) else str(when or "")


def head(
    request: Any,
    subject: str = "",
    *,
    title: str = "",
    description: str = "",
    path: str | None = None,
    image: str = "",
    image_alt: str = "",
    kind: str = "website",
    published: Any = None,
    modified: Any = None,
    images: list[dict[str, str]] | None = None,
    keywords: str = "",
    breadcrumbs: list[tuple[str, str]] | None = None,
) -> Markup:
    s = _settings(request)
    nest = request.app.state.nest
    m = _meta(request, subject)  # the page's picture, canonical, noindex
    said = _words(request, subject)  # its words, in the page's language
    translated = bool(_translated(request))
    # the site-wide description and keywords are written in the default language
    site_desc = "" if translated else str(s.get("description") or "")
    site_words = "" if translated else str(s.get("keywords") or "")
    page_title = (said.title if said and said.title else title) or nest.title
    desc = (said.description if said and said.description else description) or site_desc
    desc = " ".join(desc.split())[:300]
    words = service.keywords(
        ", ".join(x for x in ((said.keywords if said else ""), keywords, site_words) if x)
    )
    path = path if path is not None else request.url.path
    # a canonical address editors set is the original's page (a translated one is its own)
    own_canonical = m.canonical if m and m.canonical and not translated else ""
    canonical = absolute(request, own_canonical or path)
    pic = picture(request, (m.image if m and m.image else "") or image or str(s.get("image") or ""))
    hidden = bool(s.get("hidden"))
    noindex = hidden or bool(m and m.noindex)
    og_type = "article" if kind == "article" else "website"
    locale = translator(request).locale or "ro"

    tags = [f'<link rel="canonical" href="{escape(canonical)}">']
    if desc:
        tags.append(f'<meta name="description" content="{escape(desc)}">')
    if words:
        tags.append(f'<meta name="keywords" content="{escape(words)}">')
    tags.append(
        '<meta name="robots" content="noindex, nofollow">'
        if hidden
        else '<meta name="robots" content="noindex, follow">'
        if noindex
        else '<meta name="robots" content="index, follow, max-image-preview:large">'
    )
    tags += [
        f'<meta property="og:site_name" content="{escape(nest.title)}">',
        f'<meta property="og:title" content="{escape(page_title)}">',
        f'<meta property="og:url" content="{escape(canonical)}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:locale" content="{escape(og_locale(str(locale)))}">',
    ]
    if desc:
        tags.append(f'<meta property="og:description" content="{escape(desc)}">')
    if pic:
        tags.append(f'<meta property="og:image" content="{escape(pic)}">')
        if image_alt:
            tags.append(f'<meta property="og:image:alt" content="{escape(image_alt)}">')
    tags.append(
        f'<meta name="twitter:card" content="{"summary_large_image" if pic else "summary"}">'
    )
    if s.get("twitter"):
        tags.append(f'<meta name="twitter:site" content="{escape(str(s.get("twitter")))}">')
    if kind == "article" and published:
        tags.append(f'<meta property="article:published_time" content="{escape(_iso(published))}">')
        if modified:
            tags.append(
                f'<meta property="article:modified_time" content="{escape(_iso(modified))}">'
            )
    if path == "/":  # the home page proves the site is ours
        if s.get("google_verification"):
            tags.append(
                f'<meta name="google-site-verification" content="{escape(str(s.get("google_verification")))}">'
            )
        if s.get("bing_verification"):
            tags.append(
                f'<meta name="msvalidate.01" content="{escape(str(s.get("bing_verification")))}">'
            )

    if not noindex and breadcrumbs:
        tags.append(_ld(_trail(request, nest.title, breadcrumbs)))
    if not noindex:
        tags.append(
            _ld(
                _schema(
                    request,
                    kind,
                    page_title,
                    desc,
                    canonical,
                    pic,
                    published,
                    modified,
                    images or [],
                )
            )
        )
    return Markup("\n".join(tags))


def _schema(request, kind, name, desc, url, pic, published, modified, images) -> dict[str, Any]:
    nest = request.app.state.nest
    publisher = {"@type": "Organization", "name": nest.title, "url": site_url(request) + "/"}
    if kind == "article":
        data: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": name[:110],
            "mainEntityOfPage": url,
            "publisher": publisher,
        }
        if published:
            data["datePublished"] = _iso(published)
        if modified:
            data["dateModified"] = _iso(modified)
    elif kind == "gallery":
        data = {
            "@context": "https://schema.org",
            "@type": "ImageGallery",
            "name": name,
            "url": url,
            "image": [
                {
                    "@type": "ImageObject",
                    "contentUrl": picture(request, i.get("key", ""), None) or i.get("url", ""),
                    **({"name": i["title"]} if i.get("title") else {}),
                    **({"caption": i["caption"]} if i.get("caption") else {}),
                }
                for i in images[:100]
            ],
        }
    elif kind == "collection":  # a category, a tag: a page of other pages
        data = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": name,
            "url": url,
        }
    elif url.rstrip("/") == site_url(request):
        data = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": nest.title,
            "url": url,
            "publisher": publisher,
        }
    else:
        data = {"@context": "https://schema.org", "@type": "WebPage", "name": name, "url": url}
    if desc:
        data["description"] = desc
    if pic and kind != "gallery":
        data["image"] = pic
    return data
