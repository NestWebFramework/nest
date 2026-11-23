"""The push module's scheduled work: sending what is due (every 30 seconds), tidying (daily)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from nest_push import store, webpush
from nest_push.models import Job, Subscription

BATCH = 200
TRIES = 5


def contact(host: Any) -> str:
    value = str(host.settings.get("contact") or "").strip()
    if value.startswith(("mailto:", "https://")):
        return value
    site = str(getattr(host, "site_url", "") or "").strip()
    return site if site.startswith("https://") else "https://nest-framework.org"


def send(ctx: Any, post: Any = None) -> str:
    """Sends what is due. Before each, the module that scheduled it may look again (its
    recheck lookup, given the job's data): {"due": later} moves it, {"message": ...}
    changes what it says, {"drop": True} forgets it; no answer, it goes as scheduled."""
    host = ctx.host
    db = host.bound("nest.db")
    key = store.key_of(host)
    vkey = webpush.keys(host.workspace)
    who = contact(host)
    sent = moved = dropped = failed = 0
    with db.session() as s:
        due = list(
            s.execute(
                select(Job, Subscription.sealed)
                .join(Subscription, Subscription.id == Job.subscription_id)
                .where(Job.due <= store.now())
                .order_by(Job.due)
                .limit(BATCH)
            )
        )
        s.expunge_all()
    for job, sealed_sub in due:
        inside = store.unseal(key, job.sealed) or {}
        message, data = inside.get("message") or {}, inside.get("data") or {}
        if job.recheck:
            try:
                answer = host.lookup(
                    job.recheck, {"ref": job.ref, "data": data, "message": message}
                )
            except Exception:  # noqa: BLE001 - its module failed: sent as scheduled
                answer = None
            if isinstance(answer, dict):
                if answer.get("drop"):
                    _forget(db, job.id)
                    dropped += 1
                    continue
                later = answer.get("due")
                if isinstance(later, datetime) and store.utc(later) > store.now() + timedelta(
                    seconds=20
                ):
                    _move(db, key, job.id, later, answer.get("data", data), message)
                    moved += 1
                    continue
                message = answer.get("message") or message
        sub = store.unseal(key, sealed_sub)
        if not sub:
            _forget(db, job.id)
            continue
        status = webpush.send(vkey, sub, message, who, ttl=int(data.get("ttl", 1800)), post=post)
        if status in (200, 201, 202):
            _forget(db, job.id)
            sent += 1
        elif status in (404, 410):  # the browser's address is gone: all of it
            with db.session() as s, s.begin():
                s.execute(delete(Subscription).where(Subscription.id == job.subscription_id))
            failed += 1
        else:
            _retry(db, job.id)
            failed += 1
    return f"{sent} sent, {moved} moved, {dropped} dropped, {failed} failed"


def _forget(db: Any, job_id: int) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Job).where(Job.id == job_id))


def _move(db: Any, key: bytes, job_id: int, due: datetime, data: dict, message: dict) -> None:
    with db.session() as s, s.begin():
        row = s.get(Job, job_id)
        if row is not None:
            row.due = store.utc(due)
            row.sealed = store.seal(key, {"message": message, "data": data})


def _retry(db: Any, job_id: int) -> None:
    with db.session() as s, s.begin():
        row = s.get(Job, job_id)
        if row is None:
            return
        row.tries += 1
        if row.tries >= TRIES:
            s.delete(row)
        else:
            row.due = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=row.tries)


def tidy(ctx: Any) -> str:
    late, gone = store.tidy(
        ctx.host.bound("nest.db"), int(ctx.host.settings.get("forget_days") or 30)
    )
    return f"{late} overdue notifications and {gone} unused addresses deleted"
