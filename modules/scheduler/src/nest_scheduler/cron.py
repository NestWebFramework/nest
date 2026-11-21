"""Cron expressions: five fields (minute hour day month weekday), and the usual names.

    "30 3 * * *"       every day at 03:30
    "*/15 * * * *"     every quarter of an hour
    "0 9 * * 1-5"      at nine, Monday to Friday
    "0 0 1 * *"        at midnight on the first of each month
    "@hourly" "@daily" "@weekly" "@monthly" "@yearly"

Each field takes ``*``, a number, a range ``a-b``, a step ``*/n`` or ``a-b/n``, and lists
of those with commas. Weekdays are 0-6 from Sunday (7 is Sunday too); names are not taken.
As in cron, when both the day of the month and the weekday are restricted, either one
matching will do. Times are read in the scheduler's time zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

NAMES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
SEARCH_LIMIT = 366 * 24 * 60  # minutes: a year and a day; beyond that the expression never matches


class CronError(ValueError):
    pass


def _field(text: str, name: str, low: int, high: int) -> frozenset[int]:
    found: set[int] = set()
    for part in text.split(","):
        body, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{name}: a step is a number above 0, not '{step_text}'")
            step = int(step_text)
        if body == "*":
            start, end = low, high
        elif "-" in body:
            a, _, b = body.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"{name}: '{body}' is not a range")
            start, end = int(a), int(b)
        elif body.isdigit():
            start = int(body)
            end = high if step_text else start
        else:
            raise CronError(f"{name}: '{body}' is not a number, a range or *")
        if not (low <= start <= high and low <= end <= high and start <= end):
            raise CronError(f"{name}: '{part}' is outside {low}-{high}")
        found.update(range(start, end + 1, step))
    return frozenset(found)


@dataclass(frozen=True)
class Cron:
    text: str
    minute: frozenset[int]
    hour: frozenset[int]
    day: frozenset[int]
    month: frozenset[int]
    weekday: frozenset[int]  # 0-6 from Sunday
    any_day: bool
    any_weekday: bool

    def matches(self, t: datetime) -> bool:
        if t.minute not in self.minute or t.hour not in self.hour or t.month not in self.month:
            return False
        day_ok = t.day in self.day
        weekday_ok = (t.isoweekday() % 7) in self.weekday
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return weekday_ok
        if self.any_weekday:
            return day_ok
        return day_ok or weekday_ok  # cron's rule: either restricted day will do

    def next_after(self, t: datetime) -> datetime:
        """The first matching minute after ``t`` (a datetime with its zone, or naive)."""
        candidate = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(SEARCH_LIMIT):
            if candidate.month not in self.month:  # skip whole months, then whole days
                month = candidate.month % 12 + 1
                year = candidate.year + (candidate.month == 12)
                candidate = candidate.replace(year=year, month=month, day=1, hour=0, minute=0)
                continue
            if candidate.hour not in self.hour:
                candidate = candidate.replace(minute=0) + timedelta(hours=1)
                continue
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise CronError(f"'{self.text}' never comes")


def parse(text: str) -> Cron:
    raw = " ".join(text.split())
    expanded = NAMES.get(raw.lower(), raw)
    parts = expanded.split(" ")
    if len(parts) != 5:
        raise CronError(
            f"'{text}': a cron expression has five fields (minute hour day month weekday)"
        )
    values = [_field(p, n, lo, hi) for p, (n, lo, hi) in zip(parts, FIELDS, strict=True)]
    weekday = frozenset(d % 7 for d in values[4])
    return Cron(
        raw,
        values[0],
        values[1],
        values[2],
        values[3],
        weekday,
        any_day=parts[2] == "*",
        any_weekday=parts[4] == "*",
    )
