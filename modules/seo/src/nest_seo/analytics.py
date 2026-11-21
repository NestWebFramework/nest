"""Google Analytics 4 on every page of the site, when its measurement ID is set (the seo
module's google_analytics setting): Nest's own script (static/analytics.js) loads
Google's tag, after asking the visitor when analytics_consent is on; the page policy lets
Google's addresses in only then. Nothing inline, so the policy stays strict."""

from __future__ import annotations

import re
from typing import Any

MEASUREMENT = re.compile(r"^G-[A-Z0-9]{4,20}$")
# where gtag.js comes from and where it sends what it measures
SOURCES = {
    "script-src": ["https://www.googletagmanager.com"],
    "connect-src": [
        "https://www.googletagmanager.com",
        "https://*.google-analytics.com",
        "https://*.analytics.google.com",
    ],
    "img-src": ["https://www.googletagmanager.com", "https://*.google-analytics.com"],
}


def measurement_id(value: Any) -> str:
    """The ID as Google gives it (G- and letters and digits), or "" when it is not one."""
    found = str(value or "").strip().upper()
    return found if MEASUREMENT.match(found) else ""


def analytics(host: Any) -> dict[str, Any] | None:
    """What a page needs to load Google Analytics, or None when it is not set up."""
    found = measurement_id(host.settings.get("google_analytics"))
    if not found:
        return None
    for directive, sources in SOURCES.items():
        for n, source in enumerate(sources):
            host.allow_source(directive, source, slot=f"analytics-{directive}-{n}")
    return {"id": found, "consent": bool(host.settings.get("analytics_consent"))}
