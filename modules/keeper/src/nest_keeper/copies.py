"""The keeper's copies of the sites' backups, away from the sites' own disks.

Every night (keeper.fetch; or "Copy to the keeper now" on a site's page) the keeper asks
each site's agent for the backups it keeps (GET /_agent/v1/backups: name, size, SHA-256),
downloads the ones it lacks through the agent (the control token), checks each against
its size and SHA-256, and keeps the newest ``backup_keep`` per site, in
``<backup_dir>/<site>/``: the site's name, made a folder name the first time. Next to each
archive, ``<archive>.sha256`` (its SHA-256, as ``sha256sum`` writes it).

The keeper pulls: a site, or its server, never writes here and cannot delete a copy. It
works the same for a site on the keeper's server and for one on another, behind its own
Cloudflare tunnel: only the agent's https address is needed.

A copy goes back to a site through a one-time link: the keeper makes a ticket, asks the
site's host helper to restore from it, and the helper downloads the archive from the
keeper (GET <route>/backups/fetch/<ticket>) and checks its SHA-256 before anything is
replaced. A ticket is good once, for half an hour, and in this process only.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from nest_keeper import sites
from nest_keeper.models import KeeperSite, utcnow

log = logging.getLogger("nest.keeper.copies")

ARCHIVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}-\d{8}-\d{6}\.tar\.gz$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TICKET_SECONDS = 1800


def root(settings: Any, workspace: Path) -> Path | None:
    """Where the copies go (backup_dir; relative: to the keeper's workspace), or None."""
    raw = str(settings.get("backup_dir") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else workspace / path).resolve()


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60] or "site"


def _when(name: str) -> str:
    """An archive's time, from its name (``<app>-YYYYMMDD-HHMMSS.tar.gz``): what it sorts by."""
    m = re.search(r"-(\d{8}-\d{6})\.tar\.gz$", name)
    return m.group(1) if m else ""


def _folder(s: Any, row: KeeperSite, base: Path | None = None) -> str:
    """The site's folder name under backup_dir: chosen once, from its name, never reused (not
    another site's, nor one left on disk by a site removed since: its copies are not this one's)."""
    if row.backup_folder:
        return row.backup_folder
    taken = set(s.scalars(select(KeeperSite.backup_folder).where(KeeperSite.id != row.id)))
    if base is not None and base.is_dir():
        taken |= {p.name for p in base.iterdir()}
    base_name, n, name = _slug(row.name), 1, _slug(row.name)
    while name in taken:
        n += 1
        name = f"{base_name}-{n}"
    row.backup_folder = name
    return name


@dataclass
class Copy:
    name: str
    size: int
    made: datetime
    sha256: str


def local(base: Path | None, folder: str) -> list[Copy]:
    """The copies kept of a site, newest first."""
    if base is None or not folder:
        return []
    where = base / folder
    if not where.is_dir():
        return []
    out = []
    for p in where.iterdir():
        if ARCHIVE.match(p.name) and p.is_file():
            st = p.stat()
            out.append(Copy(p.name, st.st_size, datetime.fromtimestamp(st.st_mtime, UTC), _sum(p)))
    return sorted(out, key=lambda c: (_when(c.name), c.name), reverse=True)


def _sum(path: Path) -> str:
    try:
        said = path.with_name(path.name + ".sha256").read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return ""
    return said if SHA256.match(said) else ""


def find(base: Path | None, folder: str, name: str) -> Copy | None:
    if not ARCHIVE.match(name):
        return None
    return next((c for c in local(base, folder) if c.name == name), None)


def path_of(base: Path, folder: str, name: str) -> Path:
    return base / folder / name


# --- copying ----------------------------------------------------------------------------------

_running: set[int] = set()
_lock = threading.Lock()


def running(site_id: int) -> bool:
    with _lock:
        return site_id in _running


def fetch(db: Any, secret: str, site_id: int, base: Path, keep: int) -> dict[str, Any]:
    """Copy a site's backups the keeper lacks, check them, keep the newest ``keep``.
    Returns what was copied and why not, and notes it on the site."""
    with _lock:
        if site_id in _running:
            return {"copied": [], "problem": "a copy is running already"}
        _running.add(site_id)
    try:
        copied, problem = _fetch(db, secret, site_id, base, max(1, keep))
    except Exception as e:  # noqa: BLE001 - noted on the site, not raised in a job
        log.exception("copying the backups of site %s failed", site_id)
        copied, problem = [], f"failed: {e}"
    finally:
        with _lock:
            _running.discard(site_id)
    with db.session() as s, s.begin():
        row = s.get(KeeperSite, site_id)
        if row is not None:
            row.fetch_problem = problem[:500]
            if not problem:
                row.fetched_at = utcnow()
    return {"copied": copied, "problem": problem}


def _fetch(db: Any, secret: str, site_id: int, base: Path, keep: int) -> tuple[list[str], str]:
    site, token = sites.token_of(db, secret, site_id)
    if site.kind != "agent":
        return [], "a web check has no backups to copy"
    if token is None:
        return [], "no readable token: give it again in the site's settings"
    answer = sites.call(site.agent, token, "backups")
    if answer.code == 404:
        return [], "its agent does not give its backups (agent 0.2 or later is needed)"
    data = answer.data if isinstance(answer.data, dict) else {}
    if answer.code != 200 or not isinstance(data.get("backups"), list):
        return [], answer.problem or "its agent did not list its backups"
    if not data.get("download"):
        return [], "its token reads only: a control token is needed to copy its backups"
    with db.session() as s, s.begin():
        row = s.get(KeeperSite, site_id)
        if row is None:
            return [], "no such site"
        folder = _folder(s, row, base)
    where = base / folder
    where.mkdir(parents=True, exist_ok=True)
    offered = []
    for b in data["backups"]:
        name, size, digest = b.get("name"), b.get("size"), str(b.get("sha256") or "")
        well_formed = isinstance(name, str) and ARCHIVE.match(name) and SHA256.match(digest)
        if well_formed and isinstance(size, int) and size >= 0:
            offered.append((name, size, digest))
    newest = sorted(offered, key=lambda o: (_when(o[0]), o[0]), reverse=True)[:keep]
    copied, failed = [], []
    for name, size, digest in sorted(newest):
        dest = where / name
        if dest.is_file() and dest.stat().st_size == size and _sum(dest) == digest:
            continue
        problem = sites.download(
            f"{site.agent}/v1/backups/{name}", token, dest, size=size, sha256=digest
        )
        if problem:
            failed.append(f"{name}: {problem}")
            continue
        dest.with_name(name + ".sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
        copied.append(name)
    _prune(where, keep)
    if failed:
        return copied, "; ".join(failed)[:500]
    if not offered:
        return copied, "the site keeps no backup yet"
    return copied, ""


def _prune(where: Path, keep: int) -> None:
    kept = sorted(
        (p for p in where.iterdir() if ARCHIVE.match(p.name)), key=lambda p: (_when(p.name), p.name)
    )
    for old in kept[:-keep]:
        old.unlink(missing_ok=True)
        old.with_name(old.name + ".sha256").unlink(missing_ok=True)
    for stale in where.glob("*.partial"):  # a copy cut short, more than a day ago
        if time.time() - stale.stat().st_mtime > 86400:
            stale.unlink(missing_ok=True)


def fetch_all(db: Any, secret: str, base: Path, keep: int) -> tuple[int, int]:
    """Every watched site's backups copied: (sites done, sites with a problem)."""
    with db.session() as s:
        ids = list(
            s.scalars(
                select(KeeperSite.id).where(
                    KeeperSite.enabled.is_(True), KeeperSite.kind == "agent"
                )
            )
        )
    bad = 0
    for site_id in ids:
        if fetch(db, secret, site_id, base, keep)["problem"]:
            bad += 1
    return len(ids), bad


def start(db: Any, secret: str, site_id: int, base: Path, keep: int) -> bool:
    """Copy one site's backups in a thread of its own (a page does not wait for it)."""
    if running(site_id):
        return False
    threading.Thread(target=fetch, args=(db, secret, site_id, base, keep), daemon=True).start()
    return True


# --- one-time links, for a server to fetch a copy back ------------------------------------------

_tickets: dict[str, tuple[Path, str, float]] = {}  # ticket -> (archive, SHA-256, until)


def ticket(path: Path, digest: str) -> str:
    """A one-time link's secret for this archive, good for half an hour."""
    now = time.monotonic()
    with _lock:
        for t in [t for t, (_p, _d, until) in _tickets.items() if until < now]:
            del _tickets[t]
        made = secrets.token_urlsafe(32)
        _tickets[made] = (path, digest, now + TICKET_SECONDS)
    return made


def redeem(made: str) -> Path | None:
    """The archive a ticket is for, once (None: unknown, used or too old)."""
    with _lock:
        found = _tickets.pop(made, None)
    if found is None or found[2] < time.monotonic() or not found[0].is_file():
        return None
    return found[0]


def sha256_of(path: Path) -> str:
    said = _sum(path)
    if said:
        return said
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
