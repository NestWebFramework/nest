"""The scheduler: jobs at set times or intervals, for every module of an application.

A package declares its jobs in its manifest (``schedule:``, see ``nest_scheduler.jobs``);
the application may change their timing in its own. One process runs them: the one that
holds the lease, a row in the database that any worker of any container sharing it may
take when its holder stops renewing it. So a job runs once, however many workers or
containers serve the application, and a job missed while everything was down runs once
when it comes back (``catch_up: once``) or waits for its next time (``skip``).

A job is a function taking a :class:`Context`. An async one runs on the event loop
(cancelled after its ``timeout``); a blocking one (``thread: true``, the default) runs in
the scheduler's own threads (``threads``, 4), never in those that answer the pages. The
same job never runs twice at once. What it returns (a short text, a dict) is kept as its
result; what it raises fails the run, and the next one comes at its time as usual.

Game time is not this: Saga's world loop and its timers keep their own clock.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import secrets
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nest import ModuleHost
from nest_scheduler import jobs as job_specs
from nest_scheduler import store
from nest_scheduler.models import utcnow

__all__ = ["Context"]

log = logging.getLogger("nest.scheduler")
START_DELAY = 20.0  # seconds after the start before the first job (the site serves first)
POLL = 5.0  # the most it sleeps: how soon "run now" from the admin panel is seen


@dataclass
class Context:
    """What a job is given: its package's host (settings, database, workspace), the job,
    why it runs (due, catch-up, asked), and a logger."""

    host: ModuleHost
    job: job_specs.Job
    why: str
    log: logging.Logger


class Scheduler:
    def __init__(self, host: ModuleHost) -> None:
        self.host = host
        found, problems = job_specs.collect(host.sections("schedule"), host.app_name)
        self.jobs = found
        self.problems = problems
        for p in problems:
            log.warning("schedule: %s", p)
        self.holder = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}"
        self.pool: ThreadPoolExecutor | None = None
        self.running: dict[str, asyncio.Task] = {}
        self.holding = False
        self.started = time.monotonic()

    # --- time --------------------------------------------------------------------------

    def zone(self) -> ZoneInfo:
        name = str(self.host.settings.get("timezone") or "UTC")
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            log.warning("timezone '%s' is not known; UTC is used", name)
            return ZoneInfo("UTC")

    def every(self, job: job_specs.Job) -> float:
        if job.every_setting:
            owner = self.host.host_of(job.owner)
            try:
                value = float((owner.settings.get(job.every_setting) if owner else 0) or 0)
            except (TypeError, ValueError, KeyError):
                value = 0
            return max(job_specs.MIN_EVERY, value or 60)
        return job.every or 60

    def when(self, job: job_specs.Job) -> str:
        """When it runs, as people read it: "every 6h", "every 5m (check_seconds)", a cron."""
        if job.every_setting:
            return f"every {job_specs.human(self.every(job))} ({job.every_setting})"
        return job.when

    def next_time(self, job: job_specs.Job, after: datetime) -> datetime:
        """The next time after ``after`` (naive UTC), as naive UTC."""
        if job.cron is not None:
            zone = self.zone()
            local = after.replace(tzinfo=UTC).astimezone(zone)
            return job.cron.next_after(local).astimezone(UTC).replace(tzinfo=None)
        return after + timedelta(seconds=self.every(job))

    # --- the loop ----------------------------------------------------------------------

    def db(self) -> Any:
        return self.host.bound("nest.db")

    async def run_forever(self) -> None:
        await asyncio.sleep(1)
        lease_seconds = max(15.0, float(self.host.settings.get("lease_seconds") or 60))
        last_prune = 0.0
        try:
            while True:
                db = self.db()
                holds = await asyncio.to_thread(store.hold_lease, db, self.holder, lease_seconds)
                if holds and not self.holding:
                    log.info("this process (%s) runs the jobs", self.holder)
                    await asyncio.to_thread(store.clear_running, db)
                    await asyncio.to_thread(self.prepare, db)
                self.holding = holds
                if holds:
                    if time.monotonic() - self.started >= START_DELAY:
                        await self.run_due(db)
                    if time.monotonic() - last_prune > 3600:
                        days = max(1, int(self.host.settings.get("history_days") or 30))
                        await asyncio.to_thread(store.prune, db, days)
                        last_prune = time.monotonic()
                await asyncio.sleep(min(POLL, lease_seconds / 3) if holds else lease_seconds / 3)
        finally:
            if self.holding:  # another process may take over at once, not after the lease
                try:
                    store.let_go(self.db(), self.holder)
                except Exception:  # noqa: BLE001 - stopping anyway; the lease runs out
                    log.warning("could not let the lease go; it runs out by itself")

    def prepare(self, db: Any) -> None:
        """Each job's next time, at the lease's start: a new job gets its first; a missed
        one runs now (catch_up: once) or at its next time (skip); at_start ones run now."""
        now = utcnow()
        known = store.states(db)
        for key, job in self.jobs.items():
            row = known.get(key)
            if row is None:
                store.ensure(db, key, now if job.at_start else self.next_time(job, now))
                continue
            if job.at_start:
                store.set_next(db, key, now)
            elif row.next_at is None or (row.next_at < now and job.catch_up == "skip"):
                store.set_next(db, key, self.next_time(job, now))
            elif job.every is not None or job.every_setting:  # a shorter interval applies now
                cap = now + timedelta(seconds=self.every(job))
                if row.next_at > cap:
                    store.set_next(db, key, cap)

    async def run_due(self, db: Any) -> None:
        now = utcnow()
        known = await asyncio.to_thread(store.states, db)
        for key, job in self.jobs.items():
            row = known.get(key)
            if row is None or key in self.running:
                continue
            asked = bool(row.run_now)
            if not asked and (not job.enabled or row.paused):
                continue
            if not asked and (row.next_at is None or row.next_at > now):
                continue
            late = row.next_at is not None and now - row.next_at > timedelta(minutes=2)
            why = "asked" if asked else ("catch-up" if late else "due")
            self.running[key] = asyncio.create_task(self.run_one(db, job, why))

    async def run_one(self, db: Any, job: job_specs.Job, why: str) -> None:
        key = job.key
        next_at = self.next_time(job, utcnow())
        run_id = await asyncio.to_thread(store.started, db, key, why, next_at)
        started = time.monotonic()
        ok, result = True, ""
        try:
            value = await self.call(job, why)
            result = value if isinstance(value, str) else json.dumps(value, default=str)
            if value is None:
                result = ""
        except asyncio.CancelledError:
            ok, result = False, "cancelled (the application is stopping)"
            raise
        except TimeoutError:
            ok, result = False, f"stopped after {job_specs.human(job.timeout or 0)} (timeout)"
        except Exception as e:  # noqa: BLE001 - a failed job is noted; the next one comes
            ok, result = False, f"{type(e).__name__}: {e}"
            log.exception("job %s failed", key)
        finally:
            ms = int((time.monotonic() - started) * 1000)
            await asyncio.to_thread(store.finished, db, key, run_id, ok, ms, result)
            self.running.pop(key, None)

    async def call(self, job: job_specs.Job, why: str) -> Any:
        owner = self.host.host_of(job.owner)
        if owner is None:
            raise job_specs.JobError(f"{job.key}: its package is not in the application")
        fn = self.host.resolve(job.owner, job.run)
        context = Context(owner, job, why, logging.getLogger(f"nest.job.{job.key}"))
        if inspect.iscoroutinefunction(fn):
            coro = fn(context)
            return await (asyncio.wait_for(coro, job.timeout) if job.timeout else coro)
        if not job.thread:
            return fn(context)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.threads(), fn, context)

    def threads(self) -> ThreadPoolExecutor:
        if self.pool is None:
            size = max(1, min(32, int(self.host.settings.get("threads") or 4)))
            self.pool = ThreadPoolExecutor(size, thread_name_prefix="nest-job")
        return self.pool

    def stop(self) -> None:
        for task in self.running.values():
            task.cancel()
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)


def setup(host: ModuleHost) -> None:
    scheduler = Scheduler(host)
    host.state.update(scheduler=scheduler)
    host.answer("scheduler.jobs", lambda _key: scheduler.jobs)  # others may ask what runs
    from nest_scheduler.web import admin  # noqa: PLC0415

    host.admin(admin)

    if host.settings.get("enabled") is False:
        return

    @host.background
    async def scheduler_loop() -> None:
        await scheduler.run_forever()

    @host.on_shutdown
    def stop() -> None:
        scheduler.stop()
