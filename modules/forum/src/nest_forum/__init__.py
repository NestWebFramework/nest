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
    s = host.settings
    public = bool(s.get("public_read"))

    def may_follow(request: Any, name: str) -> bool:
        return public or current_user(request) is not None

    host.realtime.topic("forum.topic.*", authorize=may_follow)
    host.state.update(
        base="" if host.route in (None, "/") else host.route,
        public_read=public,
        edit_minutes=int(s.get("edit_minutes")),
        posts_per_page=int(s.get("posts_per_page")),
        topics_per_page=int(s.get("topics_per_page")),
        posts_per_minute=int(s.get("posts_per_minute")),
        realtime=host.realtime,
    )
    host.template_filter("forum_text", render_plain)
    host.mount(router)
