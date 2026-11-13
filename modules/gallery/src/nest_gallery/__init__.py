"""Photo galleries and albums: their own pages, and embeds in any page via shortcodes.

Reusable by any application: include it at a route (``/galerii``) and bind
nest.db and nest.storage. With the content module, its pages show galleries
through [gallery slug=...] and [album slug=...], and the tags WordPress's
gallery plugins left behind keep working after an import.
"""

from __future__ import annotations

from nest import ModuleHost
from nest_gallery.web import router, shortcodes

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    host.state["base"] = "" if host.route in (None, "/") else host.route
    shortcodes(host)
    host.mount(router)
