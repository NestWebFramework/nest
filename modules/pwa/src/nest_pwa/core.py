"""What the web app is made of: its icons and colour (from the theme), its manifest, the
service worker's script (with what it keeps), the Android app links."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from importlib.resources import files
from typing import Any

PAGES_CACHE = "nest-pages"
OFFLINE = "/offline"
# what the service worker never keeps or answers from its cache, besides the admin panel and
# the account pages (their routes are added): the agent's window, Nest's own endpoints
NEVER = ["/_nest", "/_agent", "/healthz"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$|^#[0-9a-fA-F]{3}$")


def _theme_pwa(nest: Any) -> tuple[str, dict]:
    """The theme in use's `pwa:` section (or a theme it is built on): its name and section."""
    for theme in nest.plan.themes:
        section = theme.manifest.raw.get("pwa")
        if isinstance(section, dict):
            return theme.name, section
    return "", {}


def icons(nest: Any) -> dict[str, str]:
    """The icons' URLs: ``svg``, ``png192``, ``png512``, ``maskable``, and the ``color``.

    From the theme's `pwa:` section, the entry of its `variant` setting (or `default`):
    ``{svg, png192, png512, maskable, color}``, file names in the theme's static folder.
    Missing, this module's own."""
    theme, section = _theme_pwa(nest)
    sets = section.get("icons") or {}
    variant = str(nest.theme_setting("variant", "") or "")
    chosen = sets.get(variant) or sets.get("default")
    if theme and isinstance(chosen, dict):
        out = {k: nest.asset(theme, v) for k, v in chosen.items() if k != "color" and v}
        out["color"] = str(chosen.get("color") or section.get("color") or "")
        if out.get("png192") and out.get("png512"):
            return out
    return {
        "svg": nest.asset("pwa", "icon.svg"),
        "png192": nest.asset("pwa", "icon-192.png"),
        "png512": nest.asset("pwa", "icon-512.png"),
        "maskable": nest.asset("pwa", "icon-maskable.png"),
        "color": str(section.get("color") or "#12355b"),
    }


def _short(name: str) -> str:
    """A name for under the icon: without its domain ending (Transportul.ro: Transportul)."""
    short = re.sub(r"\.(ro|md|org|com|net|eu)$", "", name.strip(), flags=re.I)
    return short[:24]


def shortcuts(setting: str, menu: str) -> list[tuple[str, str]]:
    """``Title = /path; ...`` (the setting, else the theme's menu): up to four, local paths."""
    out = []
    for part in (setting or menu or "").split(";"):
        title, _, path = part.partition("=")
        title, path = title.strip(), path.strip()
        if title and path.startswith("/") and not path.startswith("//"):
            out.append((title, path))
    return out[:4]


def color(value: str, fallback: str) -> str:
    value = (value or "").strip()
    return value if _HEX.match(value) else fallback


def manifest(nest: Any, settings: Any, translate: Any) -> dict[str, Any]:
    """The web app manifest (https://www.w3.org/TR/appmanifest/)."""
    pic = icons(nest)
    title = str(settings.get("name") or nest.title or nest.name)
    about = str(settings.get("description") or nest.manifest.module.description or "")
    start = str(settings.get("start_url") or "/")
    if not start.startswith("/") or start.startswith("//"):
        start = "/"
    out: dict[str, Any] = {
        "id": "/",
        "name": title,
        "short_name": str(settings.get("short_name") or _short(title)),
        "description": translate(about) if about else "",
        "lang": nest.catalogs.default,
        "dir": "ltr",
        "start_url": start,
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": color(str(settings.get("theme_color") or ""), pic["color"]),
        "background_color": color(str(settings.get("background_color") or ""), "#ffffff"),
        "prefer_related_applications": False,
        "icons": [
            {"src": pic["png192"], "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": pic["png512"], "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
    }
    if pic.get("maskable"):
        out["icons"].append(
            {"src": pic["maskable"], "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        )
    if pic.get("svg"):
        out["icons"].append(
            {"src": pic["svg"], "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
        )
    cats = [c.strip() for c in str(settings.get("categories") or "").split(",") if c.strip()]
    if cats:
        out["categories"] = cats
    menu = str(nest.theme_setting("menu", "") or "")
    found = shortcuts(str(settings.get("shortcuts") or ""), menu)
    if found:
        out["shortcuts"] = [
            {
                "name": translate(t),
                "url": p,
                "icons": [{"src": pic["png192"], "sizes": "192x192", "type": "image/png"}],
            }
            for t, p in found
        ]
    return out


def never(nest: Any) -> list[str]:
    """The paths the service worker leaves alone: the admin panel, the account pages, Nest's."""
    out = list(NEVER)
    if nest.admin_root:
        out.append(nest.admin_root.rstrip("/") or "/admin")
    auth = nest.module_url("auth")
    if auth and auth != "/":
        out.append(auth.rstrip("/"))
    return out


def worker(nest: Any, settings: Any) -> str:
    """The service worker's script: its template with what it keeps first (the offline page
    and the files it needs), the paths it leaves alone, and a version that changes whenever
    one of those does (so browsers take the new worker)."""
    pic = icons(nest)
    precache = [
        OFFLINE,
        nest.bundle_url("site"),
        nest.asset("pwa", "pwa.js"),
        pic["png192"],
    ]
    for module, path in (("htmx", "htmx.min.js"), ("htmx", "nest-htmx.js")):
        with contextlib.suppress(LookupError):  # a site without htmx
            precache.append(nest.asset(module, path))
    config = {
        "precache": precache,
        "never": never(nest),
        "offline": OFFLINE,
        "pages": max(5, min(200, int(settings.get("offline_pages") or 40))),
        "pagesCache": PAGES_CACHE,
    }
    raw = json.dumps(config, separators=(",", ":"), sort_keys=True)
    version = hashlib.sha256(raw.encode()).hexdigest()[:12]
    script = (files("nest_pwa") / "worker.js").read_text(encoding="utf-8")
    return script.replace("__VERSION__", version).replace("__CONFIG__", raw)


def asset_links(settings: Any) -> list[dict] | None:
    """/.well-known/assetlinks.json for the Android app (a Trusted Web Activity), or None."""
    package = str(settings.get("android_package") or "").strip()
    prints = [
        p.strip().upper()
        for p in re.split(r"[\s,]+", str(settings.get("android_fingerprints") or ""))
        if re.fullmatch(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){31}", p.strip())
    ]
    if not package or not prints:
        return None
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": prints,
            },
        }
    ]
