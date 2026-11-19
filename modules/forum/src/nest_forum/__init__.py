"""A forum, reusable by any application: boards, topics, posts, moderation.

Reading is public unless the application turns public_read off; posting is
for members (the auth module). A new reply is pushed over SSE to every open
copy of its topic. Posts are plain text. Moderators (the "moderator" role)
pin, lock and hide; authors edit their posts for edit_minutes.
"""

from __future__ import annotations

from typing import Any

from nest_auth import current_user

from nest import ModuleHost
from nest.text import render_plain
from nest_forum.web import router

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_forum.admin import admin

    host.state["url"] = "" if host.route in (None, "/") else host.route
    host.admin(admin)  # an overview in the admin panel

    def may_follow(request: Any, name: str) -> bool:
        return host.state["public_read"] or current_user(request) is not None

    host.realtime.topic("forum.topic.*", authorize=may_follow)
    host.state.update(
        base="" if host.route in (None, "/") else host.route,
        public_read=host.live("public_read", bool),
        edit_minutes=host.live("edit_minutes", int),
        posts_per_page=host.live("posts_per_page", int),
        topics_per_page=host.live("topics_per_page", int),
        posts_per_minute=host.live("posts_per_minute", int),
        realtime=host.realtime,
    )
    host.template_filter("forum_text", render_plain)
    host.mount(router)
