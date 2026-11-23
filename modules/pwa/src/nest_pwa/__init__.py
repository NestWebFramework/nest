"""Web app (PWA): makes a site installable, readable offline, and ready for an Android app
(a Trusted Web Activity). See module.yml."""

from __future__ import annotations

from typing import Any

from nest import ModuleHost

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_pwa import core
    from nest_pwa.web import root

    host.state.update(host=host)

    @host.context
    def _pwa(request: Any) -> dict[str, Any]:
        nest = request.app.state.nest

        def info() -> dict[str, Any]:
            pic = core.icons(nest)
            title = str(host.settings.get("name") or nest.title or nest.name)
            return {
                "title": title,
                "theme_color": core.color(
                    str(host.settings.get("theme_color") or ""), pic["color"]
                ),
                "icon": pic["png192"],
                "install": bool(host.settings.get("install_button")),
            }

        return {"pwa": info}

    host.serve_at_root(root)
