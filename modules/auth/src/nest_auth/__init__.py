"""Accounts, sign-in and server-side sessions.

Other modules protect a route with a dependency and never touch a password::

    from nest_auth import CurrentUser, require_role, require_user

    @router.get("/drafts")
    def drafts(user: CurrentUser = Depends(require_user)): ...

    @router.post("/terms/{id}/delete")
    def delete(id: int, user: CurrentUser = Depends(require_role("editor"))): ...
"""

from __future__ import annotations

from nest import ModuleHost
from nest_auth.passwords import hash_password, verify_password
from nest_auth.sessions import (
    CurrentUser,
    active_user,
    find_person,
    find_user,
    known_as,
    users_by_ids,
)
from nest_auth.throttle import make_throttle
from nest_auth.users import admin
from nest_auth.web import (
    AuthMiddleware,
    current_user,
    require_role,
    require_user,
    router,
)

__all__ = [
    "CurrentUser",
    "active_user",
    "current_user",
    "find_person",
    "find_user",
    "known_as",
    "hash_password",
    "require_role",
    "require_user",
    "users_by_ids",
    "verify_password",
]


def setup(host: ModuleHost) -> None:
    settings = host.settings
    days = int(settings.get("session_days"))
    host.state.update(
        session_days=days,
        allow_registration=host.live("allow_registration", bool),
        after_register=host.live("after_register", str),
        min_password_length=host.live("min_password_length", int),
        # counted where every worker sees it: a shared cache, else the database
        throttle=make_throttle(
            host.bound("nest.db"),
            host.bound_if("nest.cache", shared=True),
            int(settings.get("login_attempts")),
            60 * int(settings.get("lockout_minutes")),
        ),
        # an account (whatever the address: a guesser changing addresses) and an address
        # (whatever the account: one trying many) are each paused on their own
        account_throttle=make_throttle(
            host.bound("nest.db"),
            host.bound_if("nest.cache", shared=True),
            int(settings.get("account_attempts")),
            60 * int(settings.get("lockout_minutes")),
        ),
        address_throttle=make_throttle(
            host.bound("nest.db"),
            host.bound_if("nest.cache", shared=True),
            int(settings.get("address_attempts")),
            60 * int(settings.get("lockout_minutes")),
        ),
        register_throttle=make_throttle(
            host.bound("nest.db"),
            host.bound_if("nest.cache", shared=True),
            int(settings.get("registrations_per_hour")),
            3600,
        ),
        login_url=host.url("login"),
    )
    urls = {
        "login": host.url("login"),
        "logout": host.url("logout"),
        "register": host.url("register"),
        "account": host.url("account"),
    }
    host.state["urls"] = urls

    @host.context
    def _user(request):  # every page can say who is signed in
        return {"user": getattr(request.state, "user", None), "auth": urls}

    host.add_middleware(AuthMiddleware, session_days=days)
    if host.route is not None:  # sign-in pages; pulled in only as a dependency, it has none
        host.mount(router)
    host.admin(admin)  # accounts and roles, in the admin panel
