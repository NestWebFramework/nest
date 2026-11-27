"""The keeper and the host helpers (nest-host, deploy/site/): restarts, backups, upgrades,
rollbacks and restores of the sites nest-site runs, on this server and on others.

Each server is a row (Servers, in the panel): its helper's address, its token (``nh_``,
kept encrypted like the agents'), and, for a helper published through a Cloudflare tunnel,
the Cloudflare Access service token sent with every request. A watched site names its
server and its name there (``host_site``); a site without a server uses the helper of the
keeper's settings (``host_url``, ``host_token``), as before servers were kept.

Plain http is accepted only to this machine or a private network (the Docker bridge); a
helper elsewhere is reached through https (its tunnel's address).
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update

from nest_keeper import sites
from nest_keeper.models import KeeperServer, KeeperSite

ACTIONS = {
    "restart": "Restart",
    "backup": "Back up",
    "upgrade": "Upgrade",
    "rollback": "Roll back",
    "start": "Start",
    "stop": "Stop",
}


RESTORE = "restore"  # an action of its own: it names an archive


@dataclass
class Helper:
    url: str
    token: str
    headers: dict[str, str] = field(default_factory=dict)  # Cloudflare Access's, if any
    name: str = ""  # the server's name ("": the keeper's settings)


def helper(settings: Any) -> Helper | None:
    """The host helper the keeper is given, or None (no address or no token)."""
    url = str(settings.get("host_url") or "").strip().rstrip("/")
    token = str(settings.get("host_token") or "").strip()
    if not url or not token:
        return None
    return Helper(url, token)


def check_url(url: str) -> str | None:
    """Why this address will not do for the helper, or None."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "host_url: an http(s) address is needed"
    if parts.scheme == "http" and not sites._private(parts.hostname):
        return "host_url: plain http only on this machine or a private network (the Docker bridge)"
    return None


def call_host(
    h: Helper, path: str, *, method: str = "GET", who: str = "", body: dict | None = None
) -> sites.Answer:
    problem = check_url(h.url)
    if problem:
        return sites.Answer(False, problem=problem)
    extra: dict[str, Any] = {}
    if body is not None:
        extra["body"] = body
    if h.headers:
        extra["headers"] = h.headers
    return sites.call(h.url, h.token, path, method=method, timeout=15, who=who, **extra)


def state(h: Helper, site: str) -> sites.Answer:
    return call_host(h, f"sites/{urllib.parse.quote(site)}")


def start(h: Helper, site: str, action: str, who: str) -> sites.Answer:
    if action not in ACTIONS:
        return sites.Answer(False, problem=f"no action '{action}'")
    return call_host(h, f"sites/{urllib.parse.quote(site)}/{action}", method="POST", who=who)


def backups(h: Helper, site: str) -> sites.Answer:
    """The archives in the site's data folder on its server."""
    return call_host(h, f"sites/{urllib.parse.quote(site)}/backups")


def restore(h: Helper, site: str, who: str, body: dict[str, str]) -> sites.Answer:
    """Put an archive back: {"archive": name} (one on the server), or with a "ticket" and
    its "sha256", one the helper downloads from the keeper first."""
    path = f"sites/{urllib.parse.quote(site)}/{RESTORE}"
    return call_host(h, path, method="POST", who=who, body=body)


def job(h: Helper, job_id: str) -> sites.Answer:
    return call_host(h, f"jobs/{urllib.parse.quote(job_id, safe='')}")


def logs(h: Helper, site: str, lines: int = 200) -> sites.Answer:
    return call_host(h, f"sites/{urllib.parse.quote(site)}/logs?lines={int(lines)}")


# --- the servers ---------------------------------------------------------------------------

ACCESS_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


@dataclass
class Server:
    id: int
    name: str
    url: str
    has_token: bool
    token_lost: bool  # kept, but the keeper's key changed: give it again
    access_id: str
    has_access: bool
    sites: list[str] = field(default_factory=list)


def _server(row: KeeperServer, secret: str, names: list[str]) -> Server:
    return Server(
        row.id,
        row.name,
        row.url,
        bool(row.token),
        bool(row.token) and sites.unseal(secret, row.token) is None,
        row.access_id,
        bool(row.access_id and row.access_secret),
        names,
    )


def servers(db: Any, secret: str) -> list[Server]:
    with db.session() as s:
        names: dict[int, list[str]] = {}
        for sid, name in s.execute(
            select(KeeperSite.server_id, KeeperSite.name).where(KeeperSite.server_id.is_not(None))
        ):
            names.setdefault(sid, []).append(name)
        rows = s.scalars(select(KeeperServer).order_by(KeeperServer.name))
        return [_server(r, secret, sorted(names.get(r.id, []))) for r in rows]


def server(db: Any, secret: str, server_id: int) -> Server | None:
    return next((x for x in servers(db, secret) if x.id == server_id), None)


def _clean_server(name: str, url: str, token: str, access_id: str) -> tuple[str, str, str, str]:
    name = name.strip()
    if not name or len(name) > 120:
        raise sites.SiteError("a server needs a name, of at most 120 characters")
    url = sites.clean_url(url, what="helper's address")
    problem = check_url(url)
    if problem:
        raise sites.SiteError(problem)
    token = token.strip()
    if token and (not token.startswith("nh_") or len(token) > 100):
        raise sites.SiteError("the helper's token starts with nh_ (nest-host token)")
    access_id = access_id.strip()
    if access_id and not ACCESS_ID.match(access_id):
        raise sites.SiteError("Cloudflare Access: the client ID is letters, digits, dots, dashes")
    return name, url, token, access_id


def add_server(
    db: Any,
    secret: str,
    *,
    name: str,
    url: str,
    token: str,
    access_id: str = "",
    access_secret: str = "",
) -> int:
    name, url, token, access_id = _clean_server(name, url, token, access_id)
    if not token:
        raise sites.SiteError("the helper's token is needed (nest-host token, on that server)")
    access_secret = access_secret.strip()
    if bool(access_id) != bool(access_secret):
        raise sites.SiteError("Cloudflare Access: both the client ID and its secret, or neither")
    with db.session() as s, s.begin():
        row = KeeperServer(
            name=name,
            url=url,
            token=sites.seal(secret, token),
            access_id=access_id,
            access_secret=sites.seal(secret, access_secret),
        )
        s.add(row)
        s.flush()
        return row.id


def edit_server(
    db: Any,
    secret: str,
    server_id: int,
    *,
    name: str,
    url: str,
    token: str = "",
    access_id: str = "",
    access_secret: str = "",
) -> None:
    """Change a server; an empty token or Access secret keeps the one it has (an empty client
    ID takes Access off)."""
    name, url, token, access_id = _clean_server(name, url, token, access_id)
    access_secret = access_secret.strip()
    with db.session() as s, s.begin():
        row = s.get(KeeperServer, server_id)
        if row is None:
            raise sites.SiteError("no such server")
        if url != row.url and not token:
            raise sites.SiteError("a new address needs the helper's token given again")
        if access_id and not (access_secret or row.access_secret):
            raise sites.SiteError("Cloudflare Access: its client secret is needed too")
        row.name, row.url, row.access_id = name, url, access_id
        if token:
            row.token = sites.seal(secret, token)
        if not access_id:
            row.access_secret = ""
        elif access_secret:
            row.access_secret = sites.seal(secret, access_secret)


def remove_server(db: Any, server_id: int) -> bool:
    """Forget a server; its sites keep being watched, with no helper of their own."""
    with db.session() as s, s.begin():
        row = s.get(KeeperServer, server_id)
        if row is None:
            return False
        s.execute(
            update(KeeperSite).where(KeeperSite.server_id == server_id).values(server_id=None)
        )
        s.delete(row)
        return True


def helper_of(db: Any, secret: str, server_id: int) -> Helper | None:
    """A server's helper, its token and Access headers unsealed (None: no readable token)."""
    with db.session() as s:
        row = s.get(KeeperServer, server_id)
        if row is None:
            return None
        token = sites.unseal(secret, row.token)
        if not token:
            return None
        headers = {}
        access = sites.unseal(secret, row.access_secret) if row.access_id else None
        if row.access_id and access:
            headers = {"CF-Access-Client-Id": row.access_id, "CF-Access-Client-Secret": access}
        return Helper(row.url, token, headers, row.name)


def helper_for(db: Any, secret: str, settings: Any, site: sites.Site) -> Helper | None:
    """The helper that acts on this site: its server's, else the keeper's settings'."""
    if site.server_id is not None:
        return helper_of(db, secret, site.server_id)
    return helper(settings)


def about(h: Helper) -> sites.Answer:
    """The helper's own answer: its host's name, its sites, the actions it allows."""
    return call_host(h, "")
