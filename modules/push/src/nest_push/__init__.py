"""Push notifications (Web Push) for any module. See module.yml.

Another module schedules a notification for a browser it was given the endpoint of:

    host.lookup("push.schedule", {
        "endpoint": "...", "ref": "hub:city:cluj-napoca/sora|25|08:47",
        "due": datetime(...),                         # aware, or UTC
        "message": {"title": "...", "body": "...", "url": "/loc/...", "tag": "..."},
        "data": {...},                                # its own, given back to recheck
        "recheck": "hub.recheck",                     # optional: asked just before sending
    })  -> "ok" | "unknown" | "full"
    host.lookup("push.waiting", {"endpoint": ...})  -> [{ref, due, message, data}]
    host.lookup("push.cancel", {"endpoint": ..., "ref": ...})  -> bool
"""

from __future__ import annotations

from typing import Any

from nest import ModuleHost

__all__: list[str] = []


def setup(host: ModuleHost) -> None:
    from nest_push import store, webpush
    from nest_push.web import router

    host.state.update(host=host, base="" if host.route in (None, "/") else host.route)
    webpush.keys(host.workspace)  # made at the first start, the same for every worker

    def db() -> Any:
        return host.bound("nest.db")

    def schedule(q: Any) -> str | None:
        if not isinstance(q, dict) or not q.get("endpoint") or not q.get("due"):
            return None
        return store.schedule(
            db(),
            store.key_of(host),
            str(q["endpoint"]),
            str(q.get("ref") or ""),
            q["due"],
            dict(q.get("message") or {}),
            dict(q.get("data") or {}),
            str(q.get("recheck") or ""),
            int(host.settings.get("per_address") or 20),
        )

    host.answer("push.schedule", schedule)
    host.answer(
        "push.waiting",
        lambda q: (
            store.waiting(db(), store.key_of(host), str(q.get("endpoint") or ""))
            if isinstance(q, dict)
            else None
        ),
    )
    host.answer(
        "push.cancel",
        lambda q: (
            store.cancel(db(), str(q.get("endpoint") or ""), str(q.get("ref") or ""))
            if isinstance(q, dict)
            else None
        ),
    )
    host.answer("push.base", lambda _q=None: host.state["base"] or "/")
    host.mount(router)
