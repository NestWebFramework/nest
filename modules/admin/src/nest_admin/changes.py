"""A version change run in the background, so the page answers at once.

Choosing another version (or updating) downloads, checks, backs up, migrates and reloads:
it may take longer than a proxy waits for an answer (nginx, a Cloudflare Tunnel: about a
minute or two), and a request that times out shows nothing. So the change runs in a thread
of the worker that was asked, its state kept in the workspace (``run/admin-change.json``),
which every worker reads: the page polls it every two seconds, shows that it is under way,
and when it is done (and the workers made again) reloads, saying what was done.

One change at a time: a second asked while one runs is refused.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

FILE = Path("run") / "admin-change.json"
SETTLE = 4.0  # seconds after a change is done before the page reloads (the workers made again)
SHOWN = 300.0  # seconds a finished change is still told on the page


def _path(nest: Any) -> Path:
    return Path(nest.workspace) / FILE


def read(nest: Any) -> dict[str, Any] | None:
    """The last change, as the page shows it; one whose worker died while it ran is told as
    interrupted."""
    try:
        job = json.loads(_path(nest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    now = time.time()
    if job.get("state") == "running" and not _alive(int(job.get("pid") or 0)):
        job["state"] = "interrupted"
    job["elapsed"] = int(now - float(job.get("started") or now))
    finished = float(job.get("finished") or 0)
    job["settled"] = bool(finished) and now - finished >= SETTLE
    job["recent"] = job["state"] == "running" or (finished and now - finished < SHOWN)
    return job


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write(nest: Any, job: dict[str, Any]) -> None:
    path = _path(nest)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # whole, never half written


_lock = threading.Lock()


def start(
    nest: Any,
    run: Any,
    args: list[str],
    who: str,
    *,
    name: str = "",
    tab: str = "",
    loop: asyncio.AbstractEventLoop | None = None,
) -> dict[str, Any] | None:
    """Run ``run(args, who) -> (ok, lines)`` in a thread, then reload the site. The job,
    or None when another change is under way."""
    with _lock:
        now = read(nest)
        if now and now.get("state") == "running":
            return None
        job = {
            "id": uuid.uuid4().hex,
            "state": "running",
            "name": name,
            "tab": tab,
            "args": args,
            "who": who,
            "pid": os.getpid(),
            "started": time.time(),
            "finished": 0,
            "ok": False,
            "steps": [],
            "problems": [],
            "reload": "",
        }
        _write(nest, job)

    def work() -> None:
        try:
            ok, lines = run(args, who)
        except Exception as e:  # noqa: BLE001 - told on the page
            ok, lines = False, [str(e)]
        job.update(ok=ok)
        if ok:
            job["steps"] = [
                s for s in lines if "→" in s or s.startswith(("backup", "migrations", "✓"))
            ] or lines[-5:]
            job["reload"] = _reload(nest, loop)
        else:
            job["problems"] = lines
        job.update(state="done" if ok else "failed", finished=time.time())
        _write(nest, job)

    threading.Thread(target=work, name="nest-admin-change", daemon=True).start()
    return job


def _reload(nest: Any, loop: asyncio.AbstractEventLoop | None) -> str:
    """The running site made again with the change: nest serve's workers (its master
    signalled), or the application in place under nest run; "" when neither can be."""
    from nest.modules import SERVE_MASTER, reload_running  # noqa: PLC0415

    if reload_running(nest.workspace):
        return "serve"
    if os.environ.get(SERVE_MASTER):
        return ""  # a worker without its master: never only this one (see reload_app)
    reloader = getattr(nest, "reloader", None)
    if reloader is None or loop is None:
        return ""
    asyncio.run_coroutine_threadsafe(reloader.reload(), loop)
    return "process"
