"""Votes and their summaries: one vote per voter and subject (changeable, or taken back),
the summary recounted from the votes each time (a subject has few enough)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from nest_rating.models import Summary, Vote

KINDS = {"stars": range(1, 6), "helpful": (1, -1), "updown": (1, -1)}
SUBJECT = re.compile(r"^[a-z0-9_.-]+:[A-Za-z0-9_./-]{1,150}$")
COOKIE = "nest_voter"
PRINT_MOST = 3  # votes on one subject a day from one address and browser, under new cookies


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def sign(secret: str, subject: str, kind: str) -> str:
    return hmac.new(
        secret.encode(), f"rating:{kind}:{subject}".encode(), hashlib.sha256
    ).hexdigest()[:24]


def new_voter() -> str:
    return secrets.token_urlsafe(18)


def fingerprint(secret: str, address: str, agent: str, day: date | None = None) -> str:
    """A day's hash of the address and browser: the same visitor that cleared its cookie
    is known for that day; the address and browser themselves are never kept."""
    day = day or datetime.now(UTC).date()
    raw = f"{day.isoformat()}|{address}|{agent}".encode()
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()[:32]


@dataclass
class Summed:
    subject: str
    kind: str
    count: int = 0
    total: int = 0
    up: int = 0
    down: int = 0
    stars: tuple = (0, 0, 0, 0, 0)
    closed: bool = False

    @property
    def average(self) -> float | None:
        return round(self.total / self.count, 1) if self.count and self.kind == "stars" else None

    @property
    def share(self) -> int | None:
        """The share of yes (helpful), in percent."""
        n = self.up + self.down
        return round(100 * self.up / n) if n and self.kind == "helpful" else None

    @property
    def score(self) -> int:
        return self.up - self.down

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "kind": self.kind,
            "count": self.count,
            "average": self.average,
            "share": self.share,
            "score": self.score,
            "up": self.up,
            "down": self.down,
            "stars": list(self.stars),
            "closed": self.closed,
        }


def _summed(row: Summary | None, subject: str, kind: str) -> Summed:
    if row is None:
        return Summed(subject, kind)
    return Summed(
        row.subject,
        row.kind,
        row.count,
        row.total,
        row.up,
        row.down,
        tuple(row.stars or (0, 0, 0, 0, 0)),
        row.closed,
    )


def summary(db: Any, subject: str, kind: str = "stars") -> Summed:
    with db.session() as s:
        return _summed(s.get(Summary, subject), subject, kind)


def summaries(db: Any, subjects: list[str]) -> dict[str, Summed]:
    if not subjects:
        return {}
    with db.session() as s:
        rows = s.scalars(select(Summary).where(Summary.subject.in_(set(subjects))))
        return {r.subject: _summed(r, r.subject, r.kind) for r in rows}


def mine(db: Any, subject: str, voter: str) -> int | None:
    """The value this voter gave (None: none yet)."""
    if not voter:
        return None
    with db.session() as s:
        return s.scalar(select(Vote.value).where(Vote.subject == subject, Vote.voter == voter))


def _recount(s: Any, subject: str, kind: str) -> Summary:
    rows = list(s.execute(select(Vote.value).where(Vote.subject == subject)).scalars())
    row = s.get(Summary, subject)
    if row is None:
        row = Summary(subject=subject, kind=kind, updated=now(), stars=[0] * 5)
        s.add(row)
    row.kind = kind
    row.count = len(rows)
    row.total = sum(rows)
    row.up = sum(1 for v in rows if v > 0) if kind != "stars" else 0
    row.down = sum(1 for v in rows if v < 0) if kind != "stars" else 0
    row.stars = [sum(1 for v in rows if v == n) for n in range(1, 6)] if kind == "stars" else []
    row.updated = now()
    return row


def vote(db: Any, subject: str, kind: str, value: int, voter: str, print_: str = "") -> str:
    """Records (or changes, or takes back with the same value again for helpful and updown)
    a vote: "ok", "removed", "closed" or "bad"."""
    if kind not in KINDS or value not in KINDS[kind] or not SUBJECT.match(subject) or not voter:
        return "bad"
    with db.session() as s, s.begin():
        row = s.get(Summary, subject)
        if row is not None and row.closed:
            return "closed"
        mine = s.scalar(select(Vote).where(Vote.subject == subject, Vote.voter == voter))
        if mine is None and print_:
            # a new cookie on an address and browser that voted here today: a few people
            # share one address (a mobile network's) and browsers look alike, so up to
            # PRINT_MOST votes count apart; beyond, it is the same visitor clearing its
            # cookie again, and it changes its latest vote instead of adding one
            since = now() - timedelta(days=1)
            same = list(
                s.scalars(
                    select(Vote)
                    .where(Vote.subject == subject, Vote.print == print_, Vote.updated >= since)
                    .order_by(Vote.updated.desc())
                )
            )
            if len(same) >= PRINT_MOST:
                mine = same[0]
        result = "ok"
        if mine is None:
            s.add(
                Vote(
                    subject=subject,
                    kind=kind,
                    value=value,
                    voter=voter,
                    print=print_,
                    created=now(),
                    updated=now(),
                )
            )
        elif kind != "stars" and mine.value == value:
            s.delete(mine)  # the same button again: the vote taken back
            result = "removed"
        else:
            mine.value, mine.updated, mine.print = value, now(), print_ or mine.print
            mine.voter = voter
        s.flush()
        _recount(s, subject, kind)
    return result


def reset(db: Any, subject: str) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Vote).where(Vote.subject == subject))
        row = s.get(Summary, subject)
        if row is not None:
            kind = row.kind
            s.delete(row)
            s.flush()
            s.add(
                Summary(
                    subject=subject,
                    kind=kind,
                    updated=now(),
                    stars=[0] * 5 if kind == "stars" else [],
                )
            )


def close(db: Any, subject: str, closed: bool, kind: str = "stars") -> None:
    with db.session() as s, s.begin():
        row = s.get(Summary, subject) or _recount(s, subject, kind)
        row.closed = closed


def overview(db: Any, limit: int = 200) -> list[Summed]:
    with db.session() as s:
        rows = s.scalars(select(Summary).order_by(Summary.updated.desc()).limit(limit))
        return [_summed(r, r.subject, r.kind) for r in rows]


def bursts(db: Any, hours: int = 24, most: int = 20) -> list[tuple[str, int]]:
    """The day-hashes that voted on many subjects lately: a script, more likely than a person."""
    since = now() - timedelta(hours=hours)
    with db.session() as s:
        rows = s.execute(
            select(Vote.print, func.count(Vote.id))
            .where(Vote.updated >= since, Vote.print != "")
            .group_by(Vote.print)
            .having(func.count(Vote.id) >= most)
            .order_by(func.count(Vote.id).desc())
        ).all()
    return [(p, n) for p, n in rows]


def forget_print(db: Any, print_: str) -> int:
    """Deletes every vote of one day-hash (a script's), and recounts what they touched."""
    with db.session() as s, s.begin():
        touched = list(s.execute(select(Vote.subject, Vote.kind).where(Vote.print == print_)).all())
        n = s.execute(delete(Vote).where(Vote.print == print_)).rowcount or 0
        s.flush()
        for subject, kind in set(touched):
            _recount(s, subject, kind)
    return n
