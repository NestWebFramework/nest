"""Accounts without email or password: a device's session, the account's key (a link that
signs in any device), adding a device by a link or 6 digits; later passkeys and a device
PIN. See module.yml.

A site's own sign-up (a game naming a character) makes the account with
``nest_keys.start_account(request, db, name)``: the session's cookie and the key's code to
show the player once. Modules holding a player's data answer ``account.forget`` (a user id)
to remove it when an account goes.
"""

from __future__ import annotations

from nest import ModuleHost
from nest_keys.web import TooMany, key_link, start_account

__all__ = ["TooMany", "key_link", "start_account"]


def setup(host: ModuleHost) -> None:
    from nest_auth import make_throttle

    from nest_keys.web import router

    settings = host.settings
    cache = host.bound_if("nest.cache", shared=True)
    host.state.update(
        host=host,
        base="" if host.route in (None, "/") else host.route,
        play=host.live("play", str),
        after=host.live("after", str),
        device_days=host.live("device_days", int),
        # codes tried from one address (keys, pairing digits): 10 in 15 minutes
        tries=make_throttle(host.bound("nest.db"), cache, 10, 15 * 60),
        new_accounts=make_throttle(
            host.bound("nest.db"), cache, int(settings.get("new_accounts_per_day") or 3), 86400
        ),
    )
    host.mount(router)

    from nest_keys import service
    from nest_keys.web import starter

    def db():
        return host.bound("nest.db")

    # for the other modules (a game): make an account as a character is named, discard one
    # made in vain, say whether one can come back without this browser, where these pages are
    host.answer("keys.starter", lambda _key=None: starter)
    host.answer("keys.discard", lambda uid: service.discard(db(), int(uid)))
    host.answer("keys.protected", lambda uid: service.protected(db(), int(uid)))
    host.answer("keys.pages", lambda _key=None: host.state["base"] or "/")
    from nest_keys.pins import PinGate

    host.state["pin_idle_hours"] = host.live("pin_idle_hours", float)
    host.add_middleware(
        PinGate, base=host.state["base"], idle_hours=lambda: host.state["pin_idle_hours"]
    )
