"""The agent (a site's status, events, checks and actions, to a token) and the keeper's
dashboard of the sites it watches through their agents."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_agent import tokens
from nest_auth.sessions import create_user
from nest_keeper import sites

from nest import create_app

SITE = """
module: {name: satul, id: test.app.satul, type: application, version: 1.2.3}
application: {title: Satul, port: 8000, theme: base}
modules:
  - {name: agent, route: /_agent}
bind:
  nest.db: {providers: [db-sqlite]}
"""

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


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "satul"
    root.mkdir()
    (root / "module.yml").write_text(SITE, encoding="utf-8")
    read, read_kept = tokens.make()
    control, control_kept = tokens.make()
    env = {
        "NEST_APP_WORKSPACE": str(tmp_path / "ws"),
        "NEST_SATUL__AGENT__READ_TOKEN": read_kept,
        "NEST_SATUL__AGENT__CONTROL_TOKEN": control_kept,
    }
    app = create_app(root, environ=env)
    with TestClient(app) as c:
        c.read, c.control = read, control
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_tokens_are_kept_as_hashes():
    token, kept = tokens.make()
    assert token.startswith("na_") and kept.startswith("sha256:") and token not in kept
    assert tokens.scope_of(token, read=kept, control="") == "read"
    assert tokens.scope_of(token, read="", control=kept) == "control"
    assert tokens.scope_of(token, read=token, control="") is None  # never a token in clear
    assert tokens.scope_of("na_other", read=kept, control=kept) is None
    assert tokens.scope_of(token, read="", control="") is None  # no setting: nobody


def test_the_status_needs_a_token(site):
    assert site.get("/_agent/v1/status").status_code == 401
    assert site.get("/_agent/v1/status", headers=bearer("na_guess")).status_code == 401
    r = site.get("/_agent/v1/status", headers=bearer(site.read))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    st = r.json()
    assert st["app"] == {"name": "satul", "title": "Satul", "version": "1.2.3"}
    assert st["ok"] and st["scope"] == "read" and st["migrations"]["pending"] == []
    assert st["requests"]["total"] >= 2  # the refused ones are counted too
    assert {m["name"] for m in st["modules"]} >= {"agent"}
    assert st["backups"]["count"] == 0


def test_the_status_tells_what_waits_for_an_admin(site):
    from datetime import UTC, datetime, timedelta

    n = site.app.state.nest
    told = [
        {
            "key": "comments.pending",
            "label": "Comments awaiting approval",
            "count": 3,
            "oldest": datetime.now(UTC) - timedelta(hours=5),
            "path": "/admin/comments/",
        },
        {"key": "rating.bursts", "label": "Visitors with suspiciously many votes", "count": 0},
    ]
    n._lookups.setdefault("agent.attention", []).append(("test", lambda _key: told))
    st = site.get("/_agent/v1/status", headers=bearer(site.read)).json()
    (waiting,) = st["attention"]  # nothing waiting: not told
    assert waiting["key"] == "comments.pending" and waiting["count"] == 3
    assert waiting["path"] == "/admin/comments/" and 4.9 < waiting["age_hours"] < 5.1
    assert waiting["labels"]["en"] == "Comments awaiting approval"


def test_events_and_checks(site):
    import logging

    logging.getLogger("nest.test").warning("the disk is filling")
    events = site.get("/_agent/v1/events", headers=bearer(site.read)).json()
    texts = [e["text"] for e in events["events"]]
    assert any("started" in t for t in texts) and "the disk is filling" in texts
    later = site.get(f"/_agent/v1/events?after={events['last']}", headers=bearer(site.read)).json()
    assert later["events"] == []
    found = site.get("/_agent/v1/check", headers=bearer(site.read)).json()
    assert any("NEST_ENV" in f["text"] for f in found["findings"])


def test_actions_need_the_control_token(site):
    listed = site.get("/_agent/v1/actions", headers=bearer(site.read)).json()
    assert "backup" in [a["name"] for a in listed["actions"]] and listed["allowed"] is False
    assert site.post("/_agent/v1/actions/backup", headers=bearer(site.read)).status_code == 403
    assert site.post("/_agent/v1/actions/nothing", headers=bearer(site.control)).status_code == 404
    r = site.post("/_agent/v1/actions/backup", headers=bearer(site.control))
    assert r.status_code == 200 and r.json()["result"]["archive"].endswith(".tar.gz")
    st = site.get("/_agent/v1/status", headers=bearer(site.control)).json()
    assert st["backups"]["count"] == 1 and st["scope"] == "control"


def test_the_command_prints_the_token_and_the_line(tmp_path):
    root = tmp_path / "satul"
    root.mkdir()
    (root / "module.yml").write_text(SITE, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "nest.cli", "agent", "token", str(root), "--control"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    token = next(line.strip() for line in out.splitlines() if line.strip().startswith("na_"))
    line = next(line.strip() for line in out.splitlines() if "=sha256:" in line)
    name, kept = line.split("=", 1)
    assert name == "NEST_SATUL__AGENT__CONTROL_TOKEN" and kept == tokens.kept(token)


# --- the keeper watching it ---------------------------------------------------------------


def test_tokens_are_sealed_with_the_keepers_key():
    sealed = sites.seal("key-one", "na_secret")
    assert "na_secret" not in sealed and sites.unseal("key-one", sealed) == "na_secret"
    assert sites.unseal("key-two", sealed) is None


def test_addresses():
    assert sites.clean_url(" https://gari.ro/ ", what="x") == "https://gari.ro"
    for bad in ("ftp://gari.ro", "gari.ro", "https://u:p@gari.ro", "https://gari.ro/?a=1"):
        with pytest.raises(sites.SiteError):
            sites.clean_url(bad, what="x")
    sites.check_agent_url("http://127.0.0.1:8400/_agent")  # this machine: http will do
    with pytest.raises(sites.SiteError):
        sites.check_agent_url("http://gari.ro/_agent")  # elsewhere: https only


@pytest.fixture
def keeper(tmp_path, site, monkeypatch):
    """The keeper, its calls to agents answered by the site's test client."""

    def call(agent, token, path, *, method="GET", timeout=10.0):
        assert agent == "https://satul.example/_agent"
        r = site.request(method, f"/_agent/v1/{path}", headers=bearer(token))
        return sites.Answer(
            True, r.status_code, r.json(), 5, "" if r.status_code < 300 else f"HTTP {r.status_code}"
        )

    monkeypatch.setattr(sites, "call", call)
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(KEEPER, encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "kws")})
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
        c.h = {"X-CSRF-Token": c.cookies["nest_csrf"]}
        yield c


def test_the_keeper_watches_a_site(keeper, site):
    assert "No site watched yet" in keeper.get("/admin/keeper/").text
    bad = keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "Satul", "url": "https://satul.example", "token": "nope"},
        headers=keeper.h,
    )
    assert bad.status_code == 400
    r = keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "Satul", "url": "https://satul.example", "token": site.read},
        headers=keeper.h,
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].endswith("/sites/1")
    db = keeper.app.state.nest.bindings.get("nest.db")
    with db.session() as s:
        from nest_keeper.models import KeeperSite

        row = s.get(KeeperSite, 1)
        assert row.up and row.token and site.read not in row.token  # kept encrypted
        assert json.loads(row.status)["app"]["version"] == "1.2.3"
    page = keeper.get("/admin/keeper/").text
    assert "Satul" in page and "100.00%" in page and "1.2.3" in page
    assert "Waiting for you" not in page and "Te așteaptă" not in page  # nothing waits
    detail = keeper.get("/admin/keeper/sites/1").text
    assert "Back up now" in detail and "reads only" in detail and "started" in detail
    assert (
        site.read not in detail and site.read not in keeper.get("/admin/keeper/sites/1/edit").text
    )
    # a read token cannot act: the agent refuses, the keeper notes who tried
    refused = keeper.post("/admin/keeper/sites/1/actions/backup", headers=keeper.h)
    assert refused.status_code == 502
    keeper.post(
        "/admin/keeper/sites/1/edit",
        data={
            "name": "Satul",
            "url": "https://satul.example",
            "agent": "https://satul.example/_agent",
            "token": site.control,
            "enabled": "true",
        },
        headers=keeper.h,
    )
    done = keeper.post("/admin/keeper/sites/1/actions/backup", headers=keeper.h)
    assert done.status_code == 200 and ".tar.gz" in done.text and "admin@example.org" in done.text
    assert "NEST_ENV" in keeper.get("/admin/keeper/sites/1/findings").text


def test_a_site_that_does_not_answer_is_down(keeper, monkeypatch):
    keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "Satul", "url": "https://satul.example", "token": "na_x"},
        headers=keeper.h,
    )
    monkeypatch.setattr(
        sites, "call", lambda *a, **k: sites.Answer(False, problem="no answer: refused")
    )
    db = keeper.app.state.nest.bindings.get("nest.db")
    seal = keeper.app.state.nest.module_state["keeper"]["seal"]
    assert sites.check_all(db, seal) == 1
    found = sites.listing(db, seal)[0]
    assert found.state == "down" and "refused" in found.problem and found.uptime_24h == 0.0
    page = keeper.get("/admin/keeper/").text
    assert "down" in page and "refused" in page
    keeper.post("/admin/keeper/sites/1/delete", headers=keeper.h)
    assert sites.listing(db, seal) == []


def test_the_keeper_application_includes_the_dashboard():
    text = (
        Path(__file__).resolve().parents[1] / "modules/keeper/src/nest_keeper/module.yml"
    ).read_text()
    assert "check_seconds" in text and "keeper.css" in text


def test_a_web_check_watches_another_programs_instance(keeper, monkeypatch):
    seen = []

    def probe(url, timeout=10.0):
        seen.append(url)
        return sites.Answer(True, 200, None, 42)

    monkeypatch.setattr(sites, "probe", probe)
    r = keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "RoboHub", "url": "http://robohub.example", "kind": "web"},
        headers=keeper.h,
        follow_redirects=False,
    )
    assert r.status_code == 303  # no token, and plain http will do: nothing secret travels
    assert seen == ["http://robohub.example"]
    page = keeper.get("/admin/keeper/").text
    assert "RoboHub" in page and "web check" in page and "42 ms" in page
    detail = keeper.get(r.headers["location"]).text
    assert "A web check" in detail and "Production check" not in detail
    monkeypatch.setattr(
        sites, "probe", lambda url, timeout=10.0: sites.Answer(True, 503, None, 9, "HTTP 503")
    )
    db = keeper.app.state.nest.bindings.get("nest.db")
    seal = keeper.app.state.nest.module_state["keeper"]["seal"]
    sites.check_all(db, seal)
    assert sites.listing(db, seal)[0].state == "down"


def test_a_minimal_status_is_enough(keeper, monkeypatch):
    """The agent's status format asks only app and ok: another program may answer it."""
    minimal = {"app": {"name": "robohub", "version": "2.4.0"}, "ok": True}
    monkeypatch.setattr(sites, "call", lambda *a, **k: sites.Answer(True, 200, minimal, 7))
    keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "RoboHub", "url": "https://robohub.example", "token": "na_x"},
        headers=keeper.h,
    )
    assert "2.4.0" in keeper.get("/admin/keeper/").text
    detail = keeper.get("/admin/keeper/sites/1")
    assert detail.status_code == 200 and "robohub 2.4.0" in detail.text


def test_the_keeper_shows_what_waits_on_the_sites(keeper, monkeypatch):
    status = {
        "app": {"name": "satul", "version": "1.2.3"},
        "ok": True,
        "scope": "read",
        "attention": [
            {
                "key": "comments.pending",
                "count": 3,
                "age_hours": 26.0,
                "path": "/admin/comments/",
                "labels": {
                    "en": "Comments awaiting approval",
                    "ro": "Comentarii care așteaptă aprobarea",
                },
            }
        ],
    }
    monkeypatch.setattr(sites, "call", lambda *a, **k: sites.Answer(True, 200, status, 5))
    keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "Satul", "url": "https://satul.example", "token": "na_x"},
        headers=keeper.h,
    )
    page = keeper.get("/admin/keeper/").text
    assert "keeper-waiting" in page and 'href="https://satul.example/admin/comments/"' in page
    assert "Satul</strong>: 3" in page and (
        "Comments awaiting approval" in page or "Comentarii care" in page
    )
    detail = keeper.get("/admin/keeper/sites/1").text
    assert "https://satul.example/admin/comments/" in detail
