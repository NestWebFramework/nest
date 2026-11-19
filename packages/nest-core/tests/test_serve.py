"""nest serve: how an application runs in production, resolved from its manifest, the
environment and the command line; and gunicorn really running it."""

import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

from nest.manifest import load_manifest
from nest.serve import ServeError, cpus, gunicorn_options, plan

APP = """
module: {name: demo, id: test.app.demo, type: application, version: 0.1.0}
application: {title: Demo, port: 8123, theme: base}
"""


def manifest(tmp_path, extra=""):
    (tmp_path / "module.yml").write_text(textwrap.dedent(APP) + extra, encoding="utf-8")
    return load_manifest(tmp_path)


def test_the_plan_takes_the_manifest_then_the_environment_then_the_command_line(tmp_path):
    m = manifest(tmp_path, "serve: {workers: 3, threads: 12, timeout: 45, max_requests: 900}\n")
    p = plan(tmp_path, m, {}, {})
    assert (p.workers, p.threads, p.timeout, p.max_requests, p.port, p.host) == (
        3,
        12,
        45,
        900,
        8123,
        "127.0.0.1",
    )
    p = plan(tmp_path, m, {"NEST_WORKERS": "5", "NEST_THREADS": "4", "PORT": "9000"}, {})
    assert (p.workers, p.threads, p.port) == (5, 4, 9000)
    p = plan(tmp_path, m, {"NEST_WORKERS": "5"}, {"workers": "2", "host": "0.0.0.0"})
    assert (p.workers, p.host) == (2, "0.0.0.0")
    assert plan(tmp_path, manifest(tmp_path), {}, {}).workers == cpus()  # auto: the CPUs


def test_bad_values_are_refused_and_one_process_modules_get_an_engine(tmp_path):
    m = manifest(tmp_path)
    with pytest.raises(ServeError, match="workers is a number"):
        plan(tmp_path, m, {"NEST_WORKERS": "many"}, {})
    with pytest.raises(ServeError, match="threads is 1 or more"):
        plan(tmp_path, m, {}, {"threads": 0})
    p = plan(tmp_path, m, {}, {"workers": "4"}, one_process=["saga"])
    assert (
        p.workers == 4 and p.engine and "saga keeps its state in the engine process" in p.notes[0]
    )
    p = plan(tmp_path, m, {}, {"workers": "1"}, one_process=["saga"])
    assert not p.engine and not p.notes  # one worker does everything, as nest run


def test_gunicorn_is_given_nests_worker_and_renews_its_workers(tmp_path):
    options = gunicorn_options(
        plan(tmp_path, manifest(tmp_path), {"NEST_TRUSTED_PROXIES": "*"}, {"workers": "2"})
    )
    assert options["worker_class"] == "nest.serve.NestWorker" and options["workers"] == 2
    assert options["max_requests"] == 5000 and options["max_requests_jitter"] == 500
    assert options["forwarded_allow_ips"] == "*" and options["preload_app"] is False
    assert options["bind"] == "127.0.0.1:8123"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="gunicorn runs on POSIX")
def test_gunicorn_runs_the_workers_and_stops_them_gracefully(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    manifest(root)
    port = _free_port()
    nest_cmd = Path(sys.executable).with_name("nest")
    env = {**os.environ, "NEST_APP_WORKSPACE": str(tmp_path / "ws")}
    proc = subprocess.Popen(
        [
            str(nest_cmd),
            "serve",
            str(root),
            "--port",
            str(port),
            "--workers",
            "2",
            "--threads",
            "4",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                    assert r.status == 200
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("nest serve did not answer")
        children = subprocess.run(
            ["ps", "-o", "pid=", "--ppid", str(proc.pid)], capture_output=True, text=True
        )
        # the master is nest serve itself (or a child of uv); its workers are its children
        assert len(children.stdout.split()) >= 1
    finally:
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0
    assert (
        "2 workers x 4 threads" in out
        and "Booting worker" in out
        and "Shutting down: Master" in out
    )


def test_the_engine_socket_stays_short_enough(tmp_path):
    from nest.serve import SOCKET_PATH_MAX, engine_socket  # noqa: PLC0415

    assert engine_socket(tmp_path) == tmp_path / "run" / "engine.sock"
    deep = tmp_path / ("a" * 60) / ("b" * 60)
    path = engine_socket(deep)
    assert len(str(path)) <= SOCKET_PATH_MAX and path.name.startswith("nest-engine-")
    assert engine_socket(deep) == path  # the same workspace, the same socket
