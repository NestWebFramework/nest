"""The sites the keeper watches: each a deployed application with an agent.

The keeper asks each agent for its status every ``check_seconds`` (one worker does it),
keeps a row per answer for ``history_days``, and tells from them whether a site is up,
since when, and how often it was these last 24 hours and 7 days. The agent's token is
kept encrypted with a key made from the keeper's NEST_SECRET_KEY: a database copied
elsewhere does not give the tokens away (and a changed key asks for them again).

Calls go only to an http(s) address, never follow a redirect (the token would go with
it), and plain http only to this machine.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import case, delete, func, select

from nest_keeper.models import KeeperAction, KeeperCheck, KeeperSite, utcnow

TIMEOUT = 10.0
READ_LIMIT = 2 * 2**20  # an agent's answer is small; never read more than this


class SiteError(ValueError):
    pass


# --- the tokens, encrypted ------------------------------------------------------------


def _fernet(secret: str) -> Fernet:
    key = hashlib.sha256(f"{secret}:nest-keeper:agent-tokens".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret: str, token: str) -> str:
    return _fernet(secret).encrypt(token.encode()).decode() if token else ""


def unseal(secret: str, sealed: str) -> str | None:
    if not sealed:
        return None
    try:
        return _fernet(secret).decrypt(sealed.encode()).decode()
    except InvalidToken:
        return None  # the keeper's key changed: the token must be given again


# --- the addresses -----------------------------------------------------------------------


def _private(host: str) -> bool:
    """The loopback or a private network (the Docker bridge): where the host helper is."""
    if _local(host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private and not address.is_unspecified


def _local(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def clean_url(raw: str, *, what: str) -> str:
    url = raw.strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SiteError(f"{what}: an http(s) address is needed")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SiteError(f"{what}: no user, query or fragment in the address")
    if len(url) > 300:
        raise SiteError(f"{what}: at most 300 characters")
    return url


def check_agent_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "http" and not _local(parts.hostname or ""):
        raise SiteError("agent: https is needed (the token would cross the network in clear)")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect is an answer, not followed: the token stays here


_opener = urllib.request.build_opener(_NoRedirect)


@dataclass
class Answer:
    reached: bool
    code: int | None = None
    data: Any = None
    ms: int | None = None
    problem: str = ""


def call(
    agent: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    timeout: float = TIMEOUT,
    who: str = "",
) -> Answer:
    """One request to an agent (or the host helper): what it answered, or why it did not."""
    request = urllib.request.Request(
        f"{agent}/v1/{path.lstrip('/')}",
        method=method,
        data=b"" if method == "POST" else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "nest-keeper",
            **({"X-Nest-Who": who} if who else {}),
        },
    )
    started = time.monotonic()
    try:
        with _opener.open(request, timeout=timeout) as r:
            body, code = r.read(READ_LIMIT), r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(READ_LIMIT), e.code
    except (OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        return Answer(False, problem=f"no answer: {reason}"[:500])
    ms = int((time.monotonic() - started) * 1000)
    try:
        data = json.loads(body or b"null")
    except ValueError:
        data = None
    problem = ""
    if code >= 300:
        detail = data.get("detail") or data.get("error") if isinstance(data, dict) else None
        problem = f"HTTP {code}" + (f": {detail}" if detail else "")
    return Answer(True, code, data, ms, problem[:500])


# --- the sites -----------------------------------------------------------------------------


@dataclass
class Site:
    id: int
    name: str
    url: str
    agent: str
    enabled: bool
    has_token: bool
    token_lost: bool
    scope: str
    up: bool | None
    since: datetime | None
    checked_at: datetime | None
    problem: str
    status: dict[str, Any] = field(default_factory=dict)
    uptime_24h: float | None = None
    uptime_7d: float | None = None
    ms: int | None = None
    recent: list[dict[str, Any]] = field(default_factory=list)
    host_site: str = ""  # its name on the server (nest-site), for the host helper
    kind: str = "agent"  # "agent" (a Nest site) or "web" (any address)

    @property
    def state(self) -> str:
        if not self.enabled:
            return "paused"
        if self.up is None:
            return "unknown"
        if self.up:
            return "warn" if self.status and not self.status.get("ok", True) else "up"
        return "down"


def _site(row: KeeperSite, secret: str) -> Site:
    try:
        status = json.loads(row.status) if row.status else {}
    except ValueError:
        status = {}
    return Site(
        row.id,
        row.name,
        row.url,
        row.agent,
        row.enabled,
        bool(row.token),
        bool(row.token) and (row.kind or "agent") == "agent" and unseal(secret, row.token) is None,
        row.scope,
        row.up,
        row.since,
        row.checked_at,
        row.problem,
        status if isinstance(status, dict) else {},
        host_site=row.host_site or "",
        kind=row.kind or "agent",
    )


KINDS = ("agent", "web")  # a Nest site's agent; or any address, answering is all it says


def _clean(name: str, url: str, agent: str, kind: str = "agent") -> tuple[str, str, str]:
    name = name.strip()
    if not name or len(name) > 120:
        raise SiteError("a site needs a name, of at most 120 characters")
    if kind not in KINDS:
        raise SiteError(f"a site is watched through its agent or as a web address, not '{kind}'")
    url = clean_url(url, what="address")
    if kind == "web":  # no token travels: any http(s) address will do
        return name, url, clean_url(agent or url, what="checked address")
    agent = clean_url(agent or f"{url}/_agent", what="agent")
    check_agent_url(agent)
    return name, url, agent


def _clean_token(token: str, kind: str, *, required: bool) -> str:
    token = token.strip()
    if kind == "web":
        return ""
    if (required or token) and (not token.startswith("na_") or len(token) > 100):
        raise SiteError("the agent's token starts with na_ (nest agent token APP)")
    return token


HOST_SITE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def clean_host_site(raw: str) -> str:
    raw = raw.strip()
    if raw and not HOST_SITE.match(raw):
        raise SiteError("the name on the server is nest-site's: lowercase letters, digits, dashes")
    return raw


def add(
    db: Any,
    secret: str,
    *,
    name: str,
    url: str,
    agent: str = "",
    token: str = "",
    host_site: str = "",
    kind: str = "agent",
) -> int:
    name, url, agent = _clean(name, url, agent, kind)
    token = _clean_token(token, kind, required=True)
    with db.session() as s, s.begin():
        row = KeeperSite(
            name=name,
            url=url,
            agent=agent,
            kind=kind,
            token=seal(secret, token),
            status="",
            host_site=clean_host_site(host_site),
        )
        s.add(row)
        s.flush()
        return row.id


def edit(
    db: Any,
    secret: str,
    site_id: int,
    *,
    name: str,
    url: str,
    agent: str,
    token: str,
    enabled: bool,
    host_site: str = "",
) -> None:
    with db.session() as s:
        row = s.get(KeeperSite, site_id)
        if row is None:
            raise SiteError("no such site")
        kind = row.kind or "agent"
    name, url, agent = _clean(name, url, agent, kind)
    host_site = clean_host_site(host_site)
    token = _clean_token(token, kind, required=False)
    with db.session() as s, s.begin():
        row = s.get(KeeperSite, site_id)
        if row is None:
            raise SiteError("no such site")
        if kind == "agent" and agent != row.agent and not token:
            raise SiteError("a new agent address needs its token given again")
        row.name, row.url, row.agent, row.enabled = name, url, agent, enabled
        row.host_site = host_site
        if token:
            row.token, row.scope = seal(secret, token), ""


def remove(db: Any, site_id: int) -> bool:
    with db.session() as s, s.begin():
        row = s.get(KeeperSite, site_id)
        if row is None:
            return False
        s.execute(delete(KeeperCheck).where(KeeperCheck.site_id == site_id))
        s.execute(delete(KeeperAction).where(KeeperAction.site_id == site_id))
        s.delete(row)
        return True


def token_of(db: Any, secret: str, site_id: int) -> tuple[Site, str | None]:
    with db.session() as s:
        row = s.get(KeeperSite, site_id)
        if row is None:
            raise SiteError("no such site")
        return _site(row, secret), unseal(secret, row.token)


def _uptimes(s: Any, since: datetime) -> dict[int, tuple[float, int | None]]:
    rows = s.execute(
        select(
            KeeperCheck.site_id,
            func.avg(case((KeeperCheck.up, 1.0), else_=0.0)),
            func.avg(KeeperCheck.ms),
        )
        .where(KeeperCheck.at >= since)
        .group_by(KeeperCheck.site_id)
    )
    return {
        sid: (round(100 * float(up), 2), int(ms) if ms is not None else None)
        for sid, up, ms in rows
    }


def listing(db: Any, secret: str, *, recent: int = 0) -> list[Site]:
    """Every site, with its uptime over 24 hours and 7 days (and its last checks)."""
    now = utcnow()
    with db.session() as s:
        found = [_site(r, secret) for r in s.scalars(select(KeeperSite).order_by(KeeperSite.name))]
        day = _uptimes(s, now - timedelta(days=1))
        week = _uptimes(s, now - timedelta(days=7))
        for site in found:
            site.uptime_24h, site.ms = day.get(site.id, (None, None))
            site.uptime_7d = week.get(site.id, (None, None))[0]
            if recent:
                site.recent = history(s, site.id, recent)
    return found


def history(s: Any, site_id: int, limit: int) -> list[dict[str, Any]]:
    rows = s.scalars(
        select(KeeperCheck)
        .where(KeeperCheck.site_id == site_id)
        .order_by(KeeperCheck.at.desc())
        .limit(limit)
    )
    return [
        {
            "at": c.at,
            "up": c.up,
            "reached": c.reached,
            "ms": c.ms,
            "code": c.code,
            "problem": c.problem,
        }
        for c in reversed(list(rows))
    ]


def one(db: Any, secret: str, site_id: int, *, recent: int = 90) -> Site | None:
    for site in listing(db, secret):
        if site.id == site_id:
            with db.session() as s:
                site.recent = history(s, site_id, recent)
            return site
    return None


def actions_log(db: Any, site_id: int, limit: int = 30) -> list[KeeperAction]:
    with db.session() as s:
        rows = list(
            s.scalars(
                select(KeeperAction)
                .where(KeeperAction.site_id == site_id)
                .order_by(KeeperAction.at.desc())
                .limit(limit)
            )
        )
        s.expunge_all()
        return rows


# --- the checks -----------------------------------------------------------------------------


def check(db: Any, secret: str, site_id: int) -> Answer:
    """Ask one site's agent for its status now (or a web address whether it answers), and
    keep what it said."""
    site, token = token_of(db, secret, site_id)
    if site.kind == "web":
        answer = probe(site.agent)
    elif token is None:
        answer = Answer(False, problem="no readable token: give it again in the site's settings")
    else:
        answer = call(site.agent, token, "status")
    data = answer.data if isinstance(answer.data, dict) else {}
    if site.kind == "web":
        data = {}
        good = answer.reached and answer.code is not None and answer.code < 400
    else:
        good = answer.reached and answer.code == 200 and "app" in data
    up = good  # it answers and its agent speaks: up (its own "ok" says how well)
    problem = answer.problem
    if good and not data.get("ok", True):
        trouble = []
        if data.get("migrations", {}).get("pending"):
            trouble.append("migrations pending: " + ", ".join(data["migrations"]["pending"]))
        if data.get("degraded"):
            trouble.append("degraded: " + ", ".join(data["degraded"]))
        failed = [k for k, v in (data.get("checks") or {}).items() if not v]
        if failed:
            trouble.append("failing: " + ", ".join(failed))
        problem = "; ".join(trouble)[:500]
    elif answer.reached and not good and not problem:
        problem = "it answers, but not as an agent"
    now = utcnow()
    with db.session() as s, s.begin():
        row = s.get(KeeperSite, site_id)
        if row is None:
            return answer
        if row.up is None or row.up != up:
            row.since = now
        row.up, row.checked_at, row.problem = up, now, problem
        if good and data:
            row.status = json.dumps(data, default=str)[:200_000]
            row.scope = str(data.get("scope") or "")
        s.add(
            KeeperCheck(
                site_id=site_id,
                at=now,
                up=up,
                reached=answer.reached,
                ms=answer.ms,
                code=answer.code,
                version=str((data.get("app") or {}).get("version") or "")[:40],
                problem=problem,
            )
        )
    return answer


def probe(url: str, timeout: float = TIMEOUT) -> Answer:
    """A web address asked as a reader would (no token, no redirect followed): an answer
    under 400 is up. For a service without a Nest agent (another program's instance)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "nest-keeper (uptime check)", "Accept": "*/*"}
    )
    started = time.monotonic()
    try:
        with _opener.open(request, timeout=timeout) as r:
            r.read(64 * 1024)
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        return Answer(False, problem=f"no answer: {reason}"[:500])
    ms = int((time.monotonic() - started) * 1000)
    return Answer(True, code, None, ms, "" if code < 400 else f"HTTP {code}")


def check_all(db: Any, secret: str) -> int:
    with db.session() as s:
        ids = list(s.scalars(select(KeeperSite.id).where(KeeperSite.enabled.is_(True))))
    for site_id in ids:
        check(db, secret, site_id)
    return len(ids)


def prune(db: Any, days: int) -> int:
    with db.session() as s, s.begin():
        result = s.execute(
            delete(KeeperCheck).where(KeeperCheck.at < utcnow() - timedelta(days=days))
        )
        return result.rowcount or 0


def run_action(db: Any, secret: str, site_id: int, action: str, who: str) -> Answer:
    """Ask a site's agent to do something (its control token), and note who asked."""
    site, token = token_of(db, secret, site_id)
    if token is None:
        answer = Answer(False, problem="no readable token")
    else:
        quoted = urllib.parse.quote(action, safe=".-_")
        answer = call(site.agent, token, f"actions/{quoted}", method="POST", timeout=600)
    ok = answer.reached and answer.code == 200
    data = answer.data if isinstance(answer.data, dict) else {}
    result = (
        json.dumps(data.get("result"), default=str) if ok else (data.get("error") or answer.problem)
    )
    with db.session() as s, s.begin():
        s.add(
            KeeperAction(
                site_id=site_id,
                action=action[:80],
                who=who[:200],
                ok=ok,
                result=str(result or "")[:5000],
            )
        )
    return answer


def note_action(db: Any, site_id: int, action: str, who: str, ok: bool, result: str) -> None:
    """Note in the site's log an action asked elsewhere (of the host helper)."""
    with db.session() as s, s.begin():
        s.add(
            KeeperAction(
                site_id=site_id, action=action[:80], who=who[:200], ok=ok, result=str(result)[:5000]
            )
        )
