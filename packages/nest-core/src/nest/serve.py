"""``nest serve``: an application in production, as gunicorn runs a Flask one.

gunicorn's master forks the workers, replaces one that dies or stays silent past its
timeout, renews each after max_requests (with jitter, so they do not all go at once),
and reloads them one by one on SIGHUP; SIGTERM stops them gracefully. Each worker is
an asyncio server (uvicorn's worker class) with a pool of threads for the synchronous
handlers, sized by ``threads``.

Before it forks, the master makes the application once: its migrations run (or, in
production, it refuses to start behind them) and its checks pass, so a broken
application never forks; then it closes what it opened, since a database connection
must not cross a fork. The workers make their own, with NEST_MIGRATE=off.

How it runs comes from the application's ``serve:`` section, then the environment
(NEST_WORKERS, NEST_THREADS, NEST_TIMEOUT, NEST_MAX_REQUESTS, NEST_HOST, PORT,
NEST_TRUSTED_PROXIES, NEST_LOG_LEVEL), then the command line, the later winning.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nest.manifest import Manifest, Serve


class ServeError(ValueError):
    pass


@dataclass
class Plan:
    """What ``nest serve`` will run, resolved."""

    app_dir: Path
    name: str
    host: str
    port: int
    workers: int
    threads: int
    timeout: int
    graceful_timeout: int
    keepalive: int
    max_requests: int
    max_requests_jitter: int
    proxies: str
    log_level: str
    notes: list[str] = field(default_factory=list)
    engine: bool = False  # one more process holds the one-process modules (nest.engine)


def cpus() -> int:
    """The CPUs this process may use (a container's share, not the machine's)."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _int(value: Any, what: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ServeError(f"{what} is a number, not '{value}'") from None
    if number < 1:
        raise ServeError(f"{what} is 1 or more, not {number}")
    return number


def plan(
    app_dir: Path,
    manifest: Manifest,
    environ: dict[str, str],
    options: dict[str, Any],
    one_process: list[str] | None = None,
    process_local: list[str] | None = None,
    unrelayed: list[str] | None = None,
) -> Plan:
    """The manifest's serve: section, the environment over it, the options over both.
    ``one_process`` names the modules that keep their state in one process."""
    spec = manifest.serve or Serve()
    port_default = (manifest.application.port if manifest.application else None) or 8000

    def pick(key: str, env: str, default: Any) -> Any:
        if options.get(key) not in (None, ""):
            return options[key]
        if environ.get(env, "") != "":
            return environ[env]
        return default

    notes: list[str] = []
    raw_workers = pick("workers", "NEST_WORKERS", spec.workers)
    workers = cpus() if str(raw_workers) == "auto" else _int(raw_workers, "workers")
    engine = bool(one_process) and workers > 1
    if engine:
        verb = "keeps its" if len(one_process or []) == 1 else "keep their"
        notes.append(
            f"{', '.join(one_process or [])} {verb} state in the engine process, which serves "
            f"its pages; the {workers} workers serve the rest and pass those to it"
        )
    if process_local and workers > 1:
        notes.append(
            f"{', '.join(process_local)}: each worker keeps its own values "
            "(bind nest.cache to redis to share them)"
        )
    if unrelayed and workers > 1:
        notes.append(
            f"{', '.join(unrelayed)}: live updates reach only the visitors of the worker "
            "that made them (bind nest.pubsub to redis to relay them)"
        )
    return Plan(
        app_dir=app_dir,
        name=manifest.name,
        host=str(pick("host", "NEST_HOST", "127.0.0.1")),
        port=_int(pick("port", "PORT", port_default), "port"),
        workers=workers,
        threads=_int(pick("threads", "NEST_THREADS", spec.threads), "threads"),
        timeout=_int(pick("timeout", "NEST_TIMEOUT", spec.timeout), "timeout"),
        graceful_timeout=_int(spec.graceful_timeout, "graceful_timeout"),
        keepalive=_int(spec.keepalive, "keepalive"),
        max_requests=_int(
            pick("max_requests", "NEST_MAX_REQUESTS", spec.max_requests), "max_requests"
        ),
        max_requests_jitter=max(0, int(spec.max_requests_jitter)),
        proxies=str(pick("forwarded_allow_ips", "NEST_TRUSTED_PROXIES", "127.0.0.1")),
        log_level=str(pick("log_level", "NEST_LOG_LEVEL", "info")).lower(),
        notes=notes,
        engine=engine,
    )


def gunicorn_options(p: Plan) -> dict[str, Any]:
    """The plan as gunicorn's settings."""
    options: dict[str, Any] = {
        "bind": f"{p.host}:{p.port}",
        "workers": p.workers,
        "worker_class": "nest.serve.NestWorker",
        "timeout": p.timeout,
        "graceful_timeout": p.graceful_timeout,
        "keepalive": p.keepalive,
        "max_requests": p.max_requests,
        "max_requests_jitter": p.max_requests_jitter,
        "forwarded_allow_ips": p.proxies,
        "proc_name": f"nest:{p.name}",
        "loglevel": p.log_level,
        "accesslog": "-",
        "errorlog": "-",
        "preload_app": False,  # each worker makes its own application (and connections)
    }
    if Path("/dev/shm").is_dir():  # the workers' heartbeat files, kept off the disk
        options["worker_tmp_dir"] = "/dev/shm"
    return options


def preflight(app_dir: Path, environ: dict[str, str]) -> Any:
    """The application made once in the master: migrations, checks; then closed."""
    from nest.host import close_providers, create_app  # noqa: PLC0415

    nest = create_app(app_dir, environ=environ).state.nest
    close_providers(nest)  # a connection must not cross the fork
    return nest


def process_local_providers(nest: Any) -> list[str]:
    """The bound providers that keep their values in each process."""
    names = [p.name for p in nest.bindings.providers()]
    return [
        n
        for n in dict.fromkeys(names)
        if (u := nest.plan.unit(n)) is not None
        and getattr(u.entry.manifest, "process_local", False)
    ]


def unrelayed_modules(nest: Any) -> list[str]:
    """The modules with live updates, when nothing relays them between workers."""
    if nest.bindings.by_interface.get("nest.pubsub"):
        return []
    return [
        u.name
        for u in nest.plan.units
        if "realtime" in u.entry.manifest.requires.host
        and not getattr(u.entry.manifest, "one_process", False)
    ]


def one_process_modules(nest: Any) -> list[str]:
    return [u.name for u in nest.plan.units if getattr(u.entry.manifest, "one_process", False)]


class QuietChecks:
    """Leaves out of the access log the health checks from the machine itself (Docker's,
    every 30 seconds): the visitors' lines stay readable."""

    def filter(self, record: Any) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 3 and str(args[2]).split("?")[0] == "/healthz":
            return not str(args[0]).startswith(("127.0.0.1", "::1"))
        return True


try:  # the worker class needs uvicorn-worker; the planning above does not
    from uvicorn_worker import UvicornWorker

    class NestWorker(UvicornWorker):
        """uvicorn's worker for gunicorn, as Nest runs it: lifespan on (the modules'
        startup and shutdown), no Server header, the client's address from the proxies
        gunicorn believes (forwarded_allow_ips)."""

        CONFIG_KWARGS = {
            "loop": "auto",
            "http": "auto",
            "lifespan": "on",
            "server_header": False,
            "proxy_headers": True,
        }

        def init_process(self) -> None:
            import logging  # noqa: PLC0415

            logging.getLogger("uvicorn.access").addFilter(QuietChecks())
            super().init_process()

except ImportError:  # pragma: no cover - nest-core depends on it
    NestWorker = None  # type: ignore[assignment,misc]


def run(p: Plan, on_reload: Any = None) -> int:
    """gunicorn's master, with Nest's application and settings; returns when it stops.
    ``on_reload`` runs in the master on SIGHUP, before the workers are made again."""
    from gunicorn.app.base import BaseApplication  # noqa: PLC0415

    options = gunicorn_options(p)
    if on_reload is not None:
        options["on_reload"] = lambda _arbiter: on_reload()

    class Application(BaseApplication):
        def load_config(self) -> None:
            for key, value in options.items():
                self.cfg.set(key, value)

        def load(self) -> Any:
            from nest.host import app_from_env  # noqa: PLC0415 - in the worker, after the fork

            return app_from_env()

    Application().run()
    return 0


# --- the engine process -----------------------------------------------------------------


SOCKET_PATH_MAX = 100  # a Unix socket's path is at most 107 bytes on Linux, 103 on macOS


def engine_socket(workspace: Path) -> Path:
    """``run/engine.sock`` in the workspace; in the user's runtime folder when that path
    would be too long for a socket (a workspace deep in the folders)."""
    run_dir = workspace / "run"
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = run_dir / "engine.sock"
    if len(os.fsencode(path)) <= SOCKET_PATH_MAX:
        return path
    import hashlib  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    digest = hashlib.sha256(os.fsencode(workspace.resolve())).hexdigest()[:12]
    return base / f"nest-engine-{digest}.sock"


class EngineProcess:
    """``nest engine`` beside gunicorn's workers: started before them, started again if it
    stops on its own (after a pause that grows while it keeps failing), stopped after them.
    On Linux it also stops if nest serve is killed outright."""

    def __init__(self, app_dir: Path, socket: Path, environ: dict[str, str], log_level: str):
        self.socket = socket
        self.command = [
            sys.executable,
            "-c",
            "from nest.cli import main; raise SystemExit(main())",
            "engine",
            str(app_dir),
            "--socket",
            str(socket),
            "--log-level",
            log_level,
        ]
        self.environ = {**environ, "NEST_ROLE": "engine", "NEST_MIGRATE": "off"}
        self.environ.pop("NEST_ENGINE_URL", None)
        self.proc: subprocess.Popen[bytes] | None = None
        self._stopping = threading.Event()
        self._watcher: threading.Thread | None = None

    def _spawn(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.socket.unlink()  # a socket left by an engine that was killed
        self.proc = subprocess.Popen(  # noqa: S603 - our own interpreter and arguments
            self.command, env=self.environ, preexec_fn=_die_with_parent
        )
        print(f"nest serve: engine process {self.proc.pid} on {self.socket}", flush=True)

    def start(self, wait: float = 120.0) -> bool:
        """Start it and wait until it listens (its worlds loaded); False if it did not."""
        self._spawn()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            if self.socket.exists():
                break
            time.sleep(0.2)
        else:
            return False
        self._watcher = threading.Thread(target=self._watch, name="engine-watch", daemon=True)
        self._watcher.start()
        return True

    def _watch(self) -> None:
        pause = 1.0
        while not self._stopping.is_set():
            assert self.proc is not None
            began = time.monotonic()
            code = self.proc.wait()
            if self._stopping.is_set():
                return
            pause = 1.0 if time.monotonic() - began > 60 else min(pause * 2, 30.0)
            print(f"nest serve: the engine stopped ({code}); starting it again", flush=True)
            if self._stopping.wait(pause):
                return
            self._spawn()

    def restart(self) -> None:
        """TERM: it writes its worlds and stops; the watcher starts it again (a reload)."""
        if self.proc is not None and self.proc.poll() is None:
            print("nest serve: restarting the engine", flush=True)
            self.proc.terminate()

    def stop(self, timeout: float = 30.0) -> None:
        """TERM, so it writes its worlds before it goes; KILL if it takes too long."""
        self._stopping.set()
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def _die_with_parent() -> None:
    """In the child, before it runs: on Linux, a TERM when nest serve dies, however it dies."""
    try:
        import ctypes  # noqa: PLC0415

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass
