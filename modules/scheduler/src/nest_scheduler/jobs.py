"""The jobs: what the packages' manifests declare under ``schedule:``.

    schedule:
      - name: sync                      # the job is <package>.<name>: trains.sync
        run: nest_trains.jobs:sync      # a function taking the job's context (async or not)
        every: 6h                       # 30s, 15m, 6h, 1d; or
        # cron: "30 3 * * *"            # a cron expression, in the scheduler's time zone
        # every_setting: check_seconds  # the package's own setting, seconds, read each time
        at_start: false                 # run it soon after the application starts too
        catch_up: once                  # missed while down: once (run it now) or skip
        timeout: 30m                    # an async job is cancelled after it; a thread is not
        thread: true                    # true: a blocking function, run in the job threads
        description: Fetch the timetable from data.gov.ro when there is a new one.

An application changes a job in its own manifest, by the job's full name:

    schedule:
      - {job: trains.sync, every: 12h}
      - {job: keeper.prune, enabled: false}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from nest_scheduler import cron

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
INTERVAL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
MIN_EVERY = 5.0  # seconds


class JobError(ValueError):
    pass


def seconds(value: Any, what: str) -> float:
    """``30s``, ``15m``, ``6h``, ``1d`` or a number of seconds."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    match = INTERVAL.match(str(value))
    if not match:
        raise JobError(f"{what}: '{value}' is not a duration (30s, 15m, 6h, 1d)")
    return float(match.group(1)) * UNITS[match.group(2) or "s"]


@dataclass(frozen=True)
class Job:
    owner: str  # the package that declares it
    name: str
    run: str  # package.module:function
    every: float | None = None
    cron: cron.Cron | None = None
    every_setting: str | None = None
    at_start: bool = False
    catch_up: str = "once"
    timeout: float | None = None
    thread: bool = True
    enabled: bool = True
    description: str = ""
    problems: tuple[str, ...] = field(default=())

    @property
    def key(self) -> str:
        return f"{self.owner}.{self.name}"

    @property
    def when(self) -> str:
        if self.cron is not None:
            return self.cron.text
        if self.every_setting:
            return f"every {self.every_setting} seconds"
        return f"every {human(self.every or 0)}"


def human(s: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size and s % size == 0:
            return f"{int(s // size)}{unit}"
    return f"{int(s)}s"


def _job(owner: str, raw: dict[str, Any]) -> Job:
    name = str(raw.get("name") or "")
    if not NAME.match(name):
        raise JobError(f"{owner}: a job's name is lowercase letters, digits, - and _, not '{name}'")
    run = str(raw.get("run") or "")
    if ":" not in run:
        raise JobError(f"{owner}.{name}: run names a function as package.module:function")
    every = raw.get("every")
    crontab = raw.get("cron")
    every_setting = raw.get("every_setting")
    if sum(x is not None for x in (every, crontab, every_setting)) != 1:
        raise JobError(f"{owner}.{name}: give exactly one of every, cron, every_setting")
    catch_up = str(raw.get("catch_up") or "once")
    if catch_up not in ("once", "skip"):
        raise JobError(f"{owner}.{name}: catch_up is once or skip, not '{catch_up}'")
    job = Job(
        owner,
        name,
        run,
        every=seconds(every, f"{owner}.{name}") if every is not None else None,
        cron=cron.parse(str(crontab)) if crontab is not None else None,
        every_setting=str(every_setting) if every_setting else None,
        at_start=bool(raw.get("at_start", False)),
        catch_up=catch_up,
        timeout=seconds(raw["timeout"], f"{owner}.{name}") if raw.get("timeout") else None,
        thread=bool(raw.get("thread", True)),
        enabled=bool(raw.get("enabled", True)),
        description=str(raw.get("description") or ""),
    )
    if job.every is not None and job.every < MIN_EVERY:
        raise JobError(f"{owner}.{name}: every is {MIN_EVERY:g}s at least")
    return job


def _changed(job: Job, raw: dict[str, Any]) -> Job:
    """A job as the application changes it (timing, enabled, catch_up, timeout)."""
    timing = {k: raw[k] for k in ("every", "cron", "every_setting") if k in raw}
    changes: dict[str, Any] = {}
    if timing:
        if len(timing) != 1:
            raise JobError(f"{job.key}: give one of every, cron, every_setting")
        k, v = next(iter(timing.items()))
        changes |= {"every": None, "cron": None, "every_setting": None}
        if k == "every":
            changes["every"] = seconds(v, job.key)
            if changes["every"] < MIN_EVERY:
                raise JobError(f"{job.key}: every is {MIN_EVERY:g}s at least")
        elif k == "cron":
            changes["cron"] = cron.parse(str(v))
        else:
            changes["every_setting"] = str(v)
    if "enabled" in raw:
        changes["enabled"] = bool(raw["enabled"])
    if "at_start" in raw:
        changes["at_start"] = bool(raw["at_start"])
    if "catch_up" in raw:
        if raw["catch_up"] not in ("once", "skip"):
            raise JobError(f"{job.key}: catch_up is once or skip")
        changes["catch_up"] = raw["catch_up"]
    if "timeout" in raw:
        changes["timeout"] = seconds(raw["timeout"], job.key) if raw["timeout"] else None
    return replace(job, **changes)


def collect(sections: list[tuple[str, Any]], app: str) -> tuple[dict[str, Job], list[str]]:
    """Every job the packages declare, as the application changes them, and the problems."""
    jobs: dict[str, Job] = {}
    problems: list[str] = []
    changes: list[dict[str, Any]] = []
    for owner, section in sections:
        if not isinstance(section, list):
            problems.append(f"{owner}: schedule is a list of jobs")
            continue
        for raw in section:
            if not isinstance(raw, dict):
                problems.append(f"{owner}: each job in schedule is a mapping")
                continue
            if "job" in raw:  # a change to another package's job
                if owner != app:
                    problems.append(f"{owner}: only the application changes another's job")
                else:
                    changes.append(raw)
                continue
            try:
                job = _job(owner, raw)
            except (JobError, cron.CronError) as e:
                problems.append(str(e))
                continue
            if job.key in jobs:
                problems.append(f"{job.key}: declared twice")
            jobs[job.key] = job
    for raw in changes:
        key = str(raw["job"])
        if key not in jobs:
            problems.append(f"{app}: schedule changes '{key}', which no package declares")
            continue
        try:
            jobs[key] = _changed(jobs[key], raw)
        except (JobError, cron.CronError) as e:
            problems.append(str(e))
    return jobs, problems
