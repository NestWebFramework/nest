"""Redirects: kept, checked, and answered."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select, update

from nest_redirects.models import Redirect, utcnow

STATUSES = (301, 302, 307, 308, 410)


class RedirectError(ValueError):
    def __init__(self, message: str, **params: object):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


def normalize_source(source: str) -> str:
    source = (source or "").strip()
    parts = urlsplit(source)
    if parts.scheme or parts.netloc:  # an old full address: keep its path
        source = parts.path + (f"?{parts.query}" if parts.query else "")
    if not source.startswith("/") or any(ord(ch) < 32 for ch in source):
        raise RedirectError("An old address is a path on this site, starting with '/'.")
    return source[:500]


def check_target(target: str, status: int) -> str:
    target = (target or "").strip()
    if status == 410:
        return ""
    parts = urlsplit(target)
    if parts.scheme in ("http", "https") and parts.netloc:
        return target[:1000]
    if (
        target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and not parts.netloc
    ):
        return target[:1000]
    raise RedirectError("A new address is a path on this site or an http(s) address.")


def add(db: Any, source: str, target: str, status: int = 301, note: str = "") -> Redirect:
    if status not in STATUSES:
        raise RedirectError("Status {status} is not a redirect.", status=status)
    source, target = normalize_source(source), check_target(target, status)
    if source == target:
        raise RedirectError("An address cannot send to itself.")
    with db.session() as s, s.begin():
        seen, step = {source}, target
        for _ in range(10):  # follow the chain the new redirect would start
            if not step.startswith("/"):
                break
            nxt = s.scalar(select(Redirect.target).where(Redirect.source == step))
            if nxt is None:
                break
            if nxt in seen or step in seen:
                raise RedirectError("That would send visitors round in a circle.")
            seen.add(step)
            step = nxt
        r = s.scalar(select(Redirect).where(Redirect.source == source))
        if r is None:
            r = Redirect(source=source, created_at=utcnow())
            s.add(r)
        r.target, r.status, r.note = target, status, note[:200]
        s.flush()
        return r


def moved(db: Any, source: str, target: str, note: str = "") -> Redirect | None:
    """A page moved from ``source`` to ``target`` (another module says so): the old address
    sends on to the new; a redirect that sent the new address away is dropped (the page is
    there again), and those that sent to the old address now send to the new one."""
    source, target = normalize_source(source), normalize_source(target)
    if source == target:
        return None
    with db.session() as s, s.begin():
        s.execute(delete(Redirect).where(Redirect.source == target))
        for r in s.scalars(select(Redirect).where(Redirect.target == source)):
            r.target = target  # no chain of hops for old links
    try:
        return add(db, source, target, 301, note)
    except RedirectError:
        return None


def find(db: Any, path: str, query: str = "") -> Redirect | None:
    """The redirect for a request: with its query first, then the path, then the path ±'/'."""
    candidates = []
    if query:
        candidates.append(f"{path}?{query}")
    candidates.append(path)
    candidates.append(path[:-1] if path.endswith("/") and len(path) > 1 else path + "/")
    with db.session() as s:
        for c in candidates:
            r = s.scalar(select(Redirect).where(Redirect.source == c))
            if r is not None:
                return r
    return None


def hit(db: Any, redirect_id: int) -> None:
    with db.session() as s, s.begin():
        s.execute(
            update(Redirect)
            .where(Redirect.id == redirect_id)
            .values(hits=Redirect.hits + 1, last_hit=utcnow())
        )


def listing(db: Any, q: str = "", limit: int = 200) -> list[Redirect]:
    with db.session() as s:
        query = select(Redirect)
        if q:
            query = query.where(Redirect.source.ilike(f"%{q}%") | Redirect.target.ilike(f"%{q}%"))
        return list(s.scalars(query.order_by(Redirect.source).limit(limit)))


def remove(db: Any, redirect_id: int) -> None:
    with db.session() as s, s.begin():
        r = s.get(Redirect, redirect_id)
        if r is not None:
            s.delete(r)
