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
from nest_auth.sessions import CurrentUser
from nest_auth.web import (
    AuthMiddleware,
    Throttle,
    current_user,
    require_role,
    require_user,
    router,
)

__all__ = [
    "CurrentUser",
    "current_user",
    "hash_password",
    "require_role",
    "require_user",
    "verify_password",
]


def setup(host: ModuleHost) -> None:
    settings = host.settings
    days = int(settings.get("session_days"))
    host.state.update(
        session_days=days,
        allow_registration=bool(settings.get("allow_registration")),
        min_password_length=int(settings.get("min_password_length")),
        throttle=Throttle(
            int(settings.get("login_attempts")), 60 * int(settings.get("lockout_minutes"))
        ),
        login_url=host.url("login"),
    )
    urls = {
        "login": host.url("login"),
        "logout": host.url("logout"),
        "register": host.url("register"),
    }

    @host.context
    def _user(request):  # every page can say who is signed in
        return {"user": getattr(request.state, "user", None), "auth": urls}

    host.add_middleware(AuthMiddleware, session_days=days)
    host.mount(router)
