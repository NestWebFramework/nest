"""The keeper and the host helper (nest-host, deploy/site/): restarts, backups, upgrades
and rollbacks of the sites nest-site runs on the server.

The helper's address and token are the keeper's settings (``host_url``, ``host_token``: a
secret, in the environment). A watched site given its name on the server (``host_site``)
gets a Server section on its page. The helper listens on the loopback or the Docker
bridge only: plain http is accepted there, and nowhere else.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from nest_keeper import sites

ACTIONS = {
    "restart": "Restart",
    "backup": "Back up",
    "upgrade": "Upgrade",
    "rollback": "Roll back",
    "start": "Start",
    "stop": "Stop",
}


@dataclass
class Helper:
    url: str
    token: str


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


def call_host(h: Helper, path: str, *, method: str = "GET", who: str = "") -> sites.Answer:
    problem = check_url(h.url)
    if problem:
        return sites.Answer(False, problem=problem)
    return sites.call(h.url, h.token, path, method=method, timeout=15, who=who)


def state(h: Helper, site: str) -> sites.Answer:
    return call_host(h, f"sites/{urllib.parse.quote(site)}")


def start(h: Helper, site: str, action: str, who: str) -> sites.Answer:
    if action not in ACTIONS:
        return sites.Answer(False, problem=f"no action '{action}'")
    return call_host(h, f"sites/{urllib.parse.quote(site)}/{action}", method="POST", who=who)


def job(h: Helper, job_id: str) -> sites.Answer:
    return call_host(h, f"jobs/{urllib.parse.quote(job_id, safe='')}")


def logs(h: Helper, site: str, lines: int = 200) -> sites.Answer:
    return call_host(h, f"sites/{urllib.parse.quote(site)}/logs?lines={int(lines)}")
