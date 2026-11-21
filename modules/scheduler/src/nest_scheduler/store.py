"""The scheduler's database work: the lease, each job's state, its runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from nest_scheduler.models import SchedulerJob, SchedulerLease, SchedulerRun, utcnow

LEASE = "jobs"


def hold_lease(db: Any, holder: str, seconds: float) -> bool:
    """Take or renew the lease that lets one process run the jobs: any worker of any
    container sharing the database may ask; one holds it until it stops renewing."""
    now = utcnow()
    until = now + timedelta(seconds=seconds)
    with db.session() as s, s.begin():
        done = s.execute(
            update(SchedulerLease)
            .where(SchedulerLease.name == LEASE)
            .where((SchedulerLease.holder == holder) | (SchedulerLease.expires_at < now))
            .values(holder=holder, expires_at=until)
        )
        if done.rowcount:
            return True
        if s.get(SchedulerLease, LEASE) is not None:
            return False
    try:
        with db.session() as s, s.begin():
            s.add(SchedulerLease(name=LEASE, holder=holder, expires_at=until))
        return True
    except IntegrityError:  # another took it at the same moment
        return False


def let_go(db: Any, holder: str) -> None:
    with db.session() as s, s.begin():
        s.execute(
            delete(SchedulerLease)
            .where(SchedulerLease.name == LEASE)
            .where(SchedulerLease.holder == holder)
        )


def lease_holder(db: Any) -> tuple[str, datetime] | None:
    with db.session() as s:
        row = s.get(SchedulerLease, LEASE)
        return (row.holder, row.expires_at) if row and row.expires_at >= utcnow() else None


def states(db: Any) -> dict[str, SchedulerJob]:
    with db.session() as s:
        rows = list(s.scalars(select(SchedulerJob)))
        s.expunge_all()
        return {r.key: r for r in rows}


def ensure(db: Any, key: str, next_at: datetime) -> None:
    with db.session() as s, s.begin():
        if s.get(SchedulerJob, key) is None:
            s.add(SchedulerJob(key=key, next_at=next_at, last_result=""))


def set_next(db: Any, key: str, next_at: datetime | None) -> None:
    with db.session() as s, s.begin():
        s.execute(update(SchedulerJob).where(SchedulerJob.key == key).values(next_at=next_at))


def started(db: Any, key: str, why: str, next_at: datetime | None) -> int:
    now = utcnow()
    with db.session() as s, s.begin():
        s.execute(
            update(SchedulerJob)
            .where(SchedulerJob.key == key)
            .values(running_since=now, run_now=False, next_at=next_at)
        )
        run = SchedulerRun(key=key, started_at=now, why=why, result="")
        s.add(run)
        s.flush()
        return run.id


def finished(db: Any, key: str, run_id: int, ok: bool, ms: int, result: str) -> None:
    now = utcnow()
    result = result[:5000]
    with db.session() as s, s.begin():
        row = s.get(SchedulerJob, key)
        if row is not None:
            row.running_since = None
            row.last_at, row.last_ok, row.last_ms, row.last_result = now, ok, ms, result
            row.failures = 0 if ok else (row.failures or 0) + 1
        run = s.get(SchedulerRun, run_id)
        if run is not None:
            run.finished_at, run.ok, run.ms, run.result = now, ok, ms, result


def clear_running(db: Any) -> None:
    """At the lease's start: what a stopped process left running did not finish."""
    with db.session() as s, s.begin():
        s.execute(
            update(SchedulerRun)
            .where(SchedulerRun.finished_at.is_(None))
            .values(finished_at=utcnow(), ok=False, result="stopped: the process ended")
        )
        s.execute(update(SchedulerJob).values(running_since=None))


def ask(db: Any, key: str, *, run_now: bool | None = None, paused: bool | None = None) -> bool:
    values: dict[str, Any] = {}
    if run_now is not None:
        values["run_now"] = run_now
    if paused is not None:
        values["paused"] = paused
    with db.session() as s, s.begin():
        return bool(
            s.execute(update(SchedulerJob).where(SchedulerJob.key == key).values(**values)).rowcount
        )


def runs(db: Any, key: str | None = None, limit: int = 50) -> list[SchedulerRun]:
    with db.session() as s:
        q = select(SchedulerRun).order_by(SchedulerRun.started_at.desc()).limit(limit)
        if key:
            q = q.where(SchedulerRun.key == key)
        rows = list(s.scalars(q))
        s.expunge_all()
        return rows


def prune(db: Any, days: int) -> int:
    with db.session() as s, s.begin():
        done = s.execute(
            delete(SchedulerRun).where(SchedulerRun.started_at < utcnow() - timedelta(days=days))
        )
        return done.rowcount or 0
