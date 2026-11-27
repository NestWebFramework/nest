"""The keeper's scheduled jobs (with the scheduler in the application; without, its own
loop does the same): ask every watched site how it is, forget old checks, and copy the
sites' backups to the keeper."""

from __future__ import annotations

from typing import Any

from nest_keeper import copies, sites


def watch(ctx: Any) -> str:
    """keeper.watch: every check_seconds, each watched site's agent (or address) asked."""
    count = sites.check_all(ctx.host.bound("nest.db"), ctx.host.state["seal"])
    return f"{count} site(s) checked"


def prune(ctx: Any) -> str:
    """keeper.prune: checks older than history_days go."""
    days = max(1, int(ctx.host.settings.get("history_days") or 30))
    gone = sites.prune(ctx.host.bound("nest.db"), days)
    return f"{gone} old check(s) removed"


def fetch(ctx: Any) -> str:
    """keeper.fetch: each night, every site's new backups copied to backup_dir."""
    base = ctx.host.state.get("copies")
    if base is None:
        return "no backup_dir: nothing copied"
    keep = max(1, int(ctx.host.settings.get("backup_keep") or 30))
    done, bad = copies.fetch_all(ctx.host.bound("nest.db"), ctx.host.state["seal"], base, keep)
    return f"{done} site(s) copied" + (f", {bad} with a problem" if bad else "")
