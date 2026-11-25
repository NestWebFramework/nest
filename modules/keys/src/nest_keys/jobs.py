"""The keys module's scheduled job."""

from __future__ import annotations

from typing import Any


def cleanup(ctx: Any) -> str:
    from nest_keys import service

    host = ctx.host
    st = host.settings

    def forget(user_id: int) -> None:
        host.gather("account.forget", user_id)

    unprotected, inactive = service.cleanup(
        host.bound("nest.db"),
        forget,
        unprotected_days=int(st.get("unprotected_days") or 14),
        inactive_days=int(st.get("inactive_days") or 365),
    )
    return f"removed {unprotected} unprotected and {inactive} inactive accounts"
