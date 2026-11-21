"""The keeper's scheduled jobs (with the scheduler in the application; without, its own
loop does the same): ask every watched site how it is, and forget old checks."""

from __future__ import annotations

from typing import Any

from nest_keeper import sites


def watch(ctx: Any) -> str:
    """keeper.watch: every check_seconds, each watched site's agent (or address) asked."""
    count = sites.check_all(ctx.host.bound("nest.db"), ctx.host.state["seal"])
    return f"{count} site(s) checked"


def prune(ctx: Any) -> str:
    """keeper.prune: checks older than history_days go."""
    days = max(1, int(ctx.host.settings.get("history_days") or 30))
    gone = sites.prune(ctx.host.bound("nest.db"), days)
    return f"{gone} old check(s) removed"
