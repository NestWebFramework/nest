"""nest-host (deploy/site/nest-host): the keeper's restarts, backups and upgrades on the
server, through nest-site; and the keeper's Server section, against a real helper whose
nest-site is a stand-in that only says what it was asked."""

from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user

from nest import create_app

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy/site/nest-host"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("nest_host_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader("nest_host_script", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def helper(tmp_path, monkeypatch):
    nh = load_helper()
    etc, state = tmp_path / "etc", tmp_path / "state"
    etc.mkdir()
    token = "nh_" + "x" * 43
    (etc / "host.conf").write_text(
        f"TOKEN_SHA256={nh.kept(token)}\nBIND=127.0.0.1\nPORT=0\nALLOW=restart backup upgrade\n"
    )
    (etc / "gari.conf").write_text("PORT=8400\n")
    (etc / "regionalisme.conf").write_text("PORT=8200\n")
    fake = tmp_path / "nest-site"
    fake.write_text('#!/bin/sh\necho "nest-site $1 $2"\nsleep 0.3\necho "· done"\n')
    fake.chmod(0o755)
    monkeypatch.setattr(nh, "NEST_SITE", str(fake))
    monkeypatch.setattr(nh, "STATE", str(state))
    monkeypatch.setattr(nh, "_out", lambda command, timeout=10: (0, "active\n"))
    nh.Handler.config, nh.Handler.jobs, nh.Handler.failures = nh.Config(str(etc)), nh.Jobs(), {}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), nh.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield nh, f"http://127.0.0.1:{server.server_address[1]}", token, state
    server.shutdown()


def ask(url, token=None, method="GET", who=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if who:
        headers["X-Nest-Who"] = who
    request = urllib.request.Request(
        url, method=method, headers=headers, data=b"" if method == "POST" else None
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait(base, token, job_id):
    for _ in range(50):
        _code, job = ask(f"{base}/v1/jobs/{job_id}", token)
        if not job["running"]:
            return job
        time.sleep(0.1)
    raise AssertionError("the job never ended")


def test_it_wants_its_token(helper):
    _nh, base, token, _state = helper
    assert ask(f"{base}/v1/")[0] == 401
    assert ask(f"{base}/v1/", "nh_wrong")[0] == 401
    code, info = ask(f"{base}/v1/", token)
    assert code == 200 and info["sites"] == ["gari", "regionalisme"]
    assert info["allow"] == ["restart", "backup", "upgrade"]


def test_it_runs_only_listed_actions_on_known_sites(helper):
    _nh, base, token, state = helper
    assert ask(f"{base}/v1/sites/nowhere/restart", token, "POST")[0] == 404
    assert ask(f"{base}/v1/sites/..%2Fetc/restart", token, "POST")[0] == 404
    assert ask(f"{base}/v1/sites/gari/stop", token, "POST")[0] == 403  # not in ALLOW
    assert ask(f"{base}/v1/sites/gari/rm%20-rf", token, "POST")[0] in (403, 404)
    code, job = ask(f"{base}/v1/sites/gari/restart", token, "POST", who="admin@example.org")
    assert code == 202 and job["running"]
    # one job at a time per site
    assert ask(f"{base}/v1/sites/gari/backup", token, "POST")[0] == 409
    done = wait(base, token, job["id"])
    assert done["code"] == 0 and "nest-site restart gari" in done["output"]
    log = (state / "host-jobs.log").read_text()
    assert '"who": "admin@example.org"' in log and '"code": 0' in log
    code, gari = ask(f"{base}/v1/sites/gari", token)
    assert code == 200 and gari["active"] == "active" and gari["jobs"][0]["id"] == job["id"]


def test_it_refuses_a_public_address(tmp_path):
    nh = load_helper()
    (tmp_path / "host.conf").write_text(f"TOKEN_SHA256={nh.kept('nh_a')}\nBIND=0.0.0.0\n")
    with pytest.raises(SystemExit):
        nh.Config(str(tmp_path))
    (tmp_path / "host.conf").write_text(f"TOKEN_SHA256={nh.kept('nh_a')}\nBIND=8.8.8.8\n")
    with pytest.raises(SystemExit):
        nh.Config(str(tmp_path))
    (tmp_path / "host.conf").write_text("BIND=127.0.0.1\n")  # no token: it does not start
    with pytest.raises(SystemExit):
        nh.Config(str(tmp_path))


# --- the keeper's Server section ---------------------------------------------------------

STATUS = {  # what a well site's agent says
    "ok": True,
    "app": {"name": "gari", "title": "Gări", "version": "0.1.0"},
    "nest": "0.3.0",
    "python": "3.13",
    "production": True,
    "uptime_s": 60,
    "requests": {"total": 1, "errors": 0, "slow": 0, "last_error": None},
    "migrations": {"pending": []},
    "backups": {"count": 0},
    "databases": [],
    "disk": {"free_gb": 10, "total_gb": 20},
    "checks": {},
    "scope": "read",
}

KEEPER = """
module: {name: keeper, id: test.app.keeper, type: application, version: 0.1.0}
application: {title: Keeper, port: 8000, theme: base}
modules:
  - {name: keeper, route: /, config: {apps: "applications"}}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def test_the_keeper_restarts_a_site_through_the_helper(helper, tmp_path, monkeypatch):
    from nest_keeper import sites

    _nh, base, token, _state = helper
    # the site's agent is not what is tried here: it answers as a well site
    monkeypatch.setattr(
        sites,
        "call",
        lambda url, tok, path, **kw: (
            _real_call(url, tok, path, **kw) if url == base else sites.Answer(True, 200, STATUS, 3)
        ),
    )
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(KEEPER, encoding="utf-8")
    env = {
        "NEST_APP_WORKSPACE": str(tmp_path / "kws"),
        "NEST_KEEPER__KEEPER__HOST_URL": base,
        "NEST_KEEPER__KEEPER__HOST_TOKEN": token,
    }
    app = create_app(root, environ=env)
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"),
            "admin@example.org",
            "correct horse battery",
            roles=("admin",),
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "admin@example.org",
                "password": "correct horse battery",
            },
        )
        h = {"X-CSRF-Token": c.cookies["nest_csrf"]}
        bad = c.post(
            "/admin/keeper/sites/new",
            data={
                "name": "Gări",
                "url": "https://gari.example",
                "token": "na_x",
                "host_site": "../gari",
            },
            headers=h,
        )
        assert bad.status_code == 400
        c.post(
            "/admin/keeper/sites/new",
            data={
                "name": "Gări",
                "url": "https://gari.example",
                "token": "na_x",
                "host_site": "gari",
            },
            headers=h,
        )
        page = c.get("/admin/keeper/sites/1").text
        assert "nest-site@gari.service" in page and "Restart" in page and "Upgrade" in page
        assert "Roll back" not in page  # not in the helper's ALLOW
        r = c.post("/admin/keeper/sites/1/server/restart", headers=h, follow_redirects=False)
        assert r.status_code == 303 and "/server/jobs/" in r.headers["location"]
        job_id = r.headers["location"].rsplit("/", 1)[1]
        wait(base, token, job_id)
        job_page = c.get(r.headers["location"]).text
        assert "nest-site restart gari" in job_page and "admin@example.org" in job_page
        assert "server.restart" in c.get("/admin/keeper/sites/1").text  # in the actions' log
        assert c.post("/admin/keeper/sites/1/server/format", headers=h).status_code == 404
        logs = c.get("/admin/keeper/sites/1/server/logs").text
        assert "active" in logs  # the stand-in journal


def _real_call(url, token, path, **kw):
    from nest_keeper.sites import Answer

    method, who = kw.get("method", "GET"), kw.get("who", "")
    code, data = ask(f"{url}/v1/{path}", token, method, who or None)
    return Answer(True, code, data, 1, "" if code < 300 else f"HTTP {code}")


def test_plain_http_only_near():
    from nest_keeper import host

    assert host.check_url("http://127.0.0.1:8090") is None
    assert host.check_url("http://172.17.0.1:8090") is None  # the Docker bridge
    assert host.check_url("http://host.example:8090") is not None
    assert host.check_url("https://host.example:8090") is None
