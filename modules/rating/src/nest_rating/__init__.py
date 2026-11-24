"""Ratings: stars, useful-or-not and up/down votes on any module's records. See module.yml.

{{ rating("coaches.operator:flixbus", "stars", name="FlixBus", item="Organization") }}
host.lookup("rating.summary", "coaches.operator:flixbus")   -> {"average": 4.2, "count": 37, ...}
host.lookup("rating.summaries", [subject, ...])               -> {subject: {...}}
"""

from __future__ import annotations

from typing import Any

from nest import ModuleHost

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_rating import service
    from nest_rating.web import admin, router, widget

    host.state.update(host=host, base="" if host.route in (None, "/") else host.route)

    def db() -> Any:
        return host.bound("nest.db")

    @host.context
    def _rating(request: Any) -> dict[str, Any]:
        return {"rating": lambda subject, kind="stars", **kw: widget(request, subject, kind, **kw)}

    host.answer(
        "rating.summary",
        lambda subject: service.summary(db(), str(subject)).as_dict() if subject else None,
    )
    host.answer(
        "rating.summaries",
        lambda subjects: (
            {k: v.as_dict() for k, v in service.summaries(db(), list(subjects)).items()}
            if isinstance(subjects, (list, tuple, set))
            else None
        ),
    )

    def cookies(_key: object = None) -> list[dict]:
        """The voter's cookie, for the consent module: necessary (set only when the visitor
        votes, so the same visitor counts once)."""
        return [
            {
                "name": service.COOKIE,
                "purpose": "necessary",
                "service": "rating",
                "provider": "",
                "owner": "rating",
                "duration": "1 year",
                "description": "Set when you vote (stars, useful or not): counts your vote once, and lets you change it.",
            }
        ]

    host.answer("consent.cookies", cookies)
    host.mount(router)
    host.admin(admin)
