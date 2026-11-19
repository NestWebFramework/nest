"""Comments on anything: a page embeds {{ comments("module.kind:id") }}.

The subject is a name, not a foreign key, so any module's records can be
commented without the comments module knowing them; the form carries the
subject signed, so nobody can post to one a page did not offer. Comments are
plain text. Guests (when allowed) wait for a moderator; robots meet a
honeypot, a minimum time and a limit per address.
"""

from __future__ import annotations

from nest import ModuleHost
from nest.text import render_plain
from nest_comments.service import Node, forget_module, thread
from nest_comments.web import admin, router, thread_html

__all__ = ["Node", "thread", "thread_html"]


def setup(host: ModuleHost) -> None:
    base = "" if host.route in (None, "/") else host.route
    host.state.update(
        action=base,
        allow_guests=host.live("allow_guests", bool),
        moderation=host.live("moderation"),
        max_depth=host.live("max_depth", int),
        min_seconds=host.live("min_seconds", float),
        per_hour=host.live("per_hour", int),
        login="/",
    )

    host.template_filter("plain", render_plain)
    # a module uninstalled from the application: the threads on its records go too
    db = host.bound("nest.db")
    host.answer("module.removed", lambda name: forget_module(db, str(name)))

    @host.context
    def _comments(request):
        return {"comments": lambda subject: thread_html(request, subject)}

    host.mount(router)
    host.admin(admin)  # moderation, in the admin panel
