"""Private conversations between members, reusable by any application.

Only participants see a conversation (anyone else gets a 404). Each member has
a channel of their own, messages.user.<id>, which only they may follow: a new
message appears in their open conversation and their inbox refreshes. A page
can show the unread count with {% include "messages/badge.html" %}.
"""

from __future__ import annotations

from typing import Any

from nest_auth import current_user

from nest import ModuleHost
from nest.text import render_plain
from nest_messages import service
from nest_messages.web import router

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    db = host.bound("nest.db")
    base = "" if host.route in (None, "/") else host.route

    def own_channel(request: Any, name: str) -> bool:
        user = current_user(request)
        return user is not None and name == f"messages.user.{user.id}"

    host.realtime.topic("messages.user.*", authorize=own_channel)
    host.state.update(
        base=base,
        realtime=host.realtime,
        max_recipients=host.live("max_recipients", int),
        per_hour=host.live("per_hour", int),
    )
    host.template_filter("message_text", render_plain)

    @host.context
    def _messages(request: Any) -> dict[str, Any]:
        def unread() -> int:
            user = current_user(request)
            return service.unread_count(db, user.id) if user else 0

        return {"unread_messages": unread, "messages_url": base or "/"}

    host.mount(router)
