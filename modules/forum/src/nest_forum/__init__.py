"""A forum, reusable by any application: boards, topics, posts, moderation.

Reading is public unless the application turns public_read off; posting is
for members (the auth module). A board with a scope is its members' only: the
application says who they are (forum.access), and another module has such a board
made when it is first wanted (lookup forum.board: {"scope", "title", "slug"?,
"description"?} -> {"slug", "url"}). A new reply is pushed over SSE to every open
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

    @host.context
    def _forum_block(request: Any) -> dict[str, Any]:
        from nest_forum import service  # noqa: PLC0415

        def forum_latest(n: Any = 5) -> list[Any]:
            """The newest public topics (the forum's block): [(topic, board)]."""
            try:
                count = int(n or 5)
            except (TypeError, ValueError):
                count = 5
            return service.latest_topics(host.bound("nest.db"), count)

        return {"forum_latest": forum_latest}

    def may_follow(request: Any, name: str) -> bool:
        """A topic's live replies, to those who may read its board."""
        from nest_forum import service  # noqa: PLC0415
        from nest_forum.web import access  # noqa: PLC0415

        try:
            topic_id = int(name.rsplit(".", 1)[1])
        except (IndexError, ValueError):
            return False
        db = host.bound("nest.db")
        t = service.topic(db, topic_id)
        b = service.board_by_id(db, t.board_id) if t is not None else None
        if b is None:
            return False
        ask = lambda key: host.lookup("forum.access", key)  # noqa: E731
        return access(ask, current_user(request), b, host.state["public_read"])[0]

    def board_for(key: Any) -> dict[str, str] | None:
        """forum.board: a board with this scope, made if missing, and its address."""
        from nest_forum import service  # noqa: PLC0415

        if not isinstance(key, dict) or not key.get("scope") or not key.get("title"):
            return None
        b = service.ensure_board(
            host.bound("nest.db"),
            str(key["title"]),
            slug=str(key.get("slug") or key["title"]),
            description=str(key.get("description") or ""),
            scope=str(key["scope"]),
        )
        return {"slug": b.slug, "url": f"{host.state['base']}/{b.slug}/"}

    host.realtime.topic("forum.topic.*", authorize=may_follow)
    host.answer("forum.board", board_for)
    host.state.update(
        base="" if host.route in (None, "/") else host.route,
        public_read=host.live("public_read", bool),
        edit_minutes=host.live("edit_minutes", int),
        posts_per_page=host.live("posts_per_page", int),
        topics_per_page=host.live("topics_per_page", int),
        posts_per_minute=host.live("posts_per_minute", int),
        public_names=host.live("public_names", str),
        realtime=host.realtime,
    )
    host.template_filter("forum_text", render_plain)
    host.mount(router)
