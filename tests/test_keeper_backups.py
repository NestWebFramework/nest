"""The sites' backups kept by the keeper, and put back: the agent lists and gives its
backups, the keeper copies them (each checked, the newest kept), its servers' host helpers
restore an archive (one on the server, or the keeper's copy through a one-time link)."""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
import time
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_keeper import copies, host, sites
from test_agent import KEEPER, bearer, site  # noqa: F401 - site is a fixture
from test_nest_host import ask, load_helper, wait

from nest import create_app

# --- the agent ------------------------------------------------------------------------------


def _backup(site_client) -> str:
    r = site_client.post("/_agent/v1/actions/backup", headers=bearer(site_client.control))
    assert r.status_code == 200, r.text
    return r.json()["result"]["archive"]


def test_the_agent_lists_its_backups_and_gives_them_to_the_control_token(site):  # noqa: F811
    name = _backup(site)
    listed = site.get("/_agent/v1/backups", headers=bearer(site.read)).json()
    (b,) = listed["backups"]
    assert b["name"] == name and b["size"] > 0 and len(b["sha256"]) == 64
    assert listed["download"] is False  # the read token lists, never downloads
    assert site.get(f"/_agent/v1/backups/{name}", headers=bearer(site.read)).status_code == 403
    assert site.get(f"/_agent/v1/backups/{name}").status_code == 401
    r = site.get(f"/_agent/v1/backups/{name}", headers=bearer(site.control))
    assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == b["sha256"]
    assert r.headers["cache-control"] == "no-store"
    for bad in ("nowhere-20260101-000000.tar.gz", "..%2Fdata%2Fsettings.conf", "x.partial"):
        assert site.get(f"/_agent/v1/backups/{bad}", headers=bearer(site.control)).status_code in (
            404,
            422,
        )
    assert site.get("/_agent/v1/backups", headers=bearer(site.control)).json()["download"]


def test_the_agent_keeps_as_many_as_nest_site():
    import yaml

    raw = yaml.safe_load(
        (Path(__file__).parents[1] / "modules/agent/src/nest_agent/module.yml").read_text()
    )
    assert raw["settings"]["backup_keep"]["default"] == 14  # nest-site's KEEP: neither prunes


# --- the keeper's copies ----------------------------------------------------------------------


@pytest.fixture
def keeper(tmp_path, site, monkeypatch):  # noqa: F811
    """The keeper with a backup_dir, its calls to the agent answered by the site's client."""

    def call(agent, token, path, *, method="GET", timeout=10.0, **_kw):
        r = site.request(method, f"/_agent/v1/{path}", headers=bearer(token))
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return sites.Answer(True, r.status_code, data, 5, "" if r.status_code < 300 else "HTTP")

    def download(url, token, dest, *, size, sha256):
        path = urllib.parse.urlsplit(url).path
        r = site.get(path, headers=bearer(token))
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        if len(r.content) != size or hashlib.sha256(r.content).hexdigest() != sha256:
            return "its SHA-256 is not the one it was said to have"
        dest.write_bytes(r.content)
        return ""

    monkeypatch.setattr(sites, "call", call)
    monkeypatch.setattr(sites, "download", download)
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(KEEPER, encoding="utf-8")
    env = {
        "NEST_APP_WORKSPACE": str(tmp_path / "kws"),
        "NEST_KEEPER__KEEPER__BACKUP_DIR": "site-backups",
        "NEST_KEEPER__KEEPER__BACKUP_KEEP": "2",
    }
    app = create_app(root, environ=env)
    with TestClient(app) as c:
        _sign_in(c, app)
        c.base = tmp_path / "kws" / "site-backups"
        yield c


def _sign_in(c, app):
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


def _until(test, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if test():
            return
        time.sleep(0.05)
    raise AssertionError("it never happened")


def test_the_keeper_copies_the_backups_checked_and_keeps_the_newest(keeper, site):  # noqa: F811
    keeper.post(
        "/admin/keeper/sites/new",
        data={"name": "Satul Mare", "url": "https://satul.example", "token": site.read},
        headers=keeper.h,
    )
    _backup(site)
    keeper.post("/admin/keeper/sites/1/fetch", headers=keeper.h)
    _until(lambda: not copies.running(1))
    page = keeper.get("/admin/keeper/sites/1").text
    assert "Copies at the keeper" in page and "a control token is needed" in page
    keeper.post(
        "/admin/keeper/sites/1/edit",
        data={
            "name": "Satul Mare",
            "url": "https://satul.example",
            "agent": "https://satul.example/_agent",
            "token": site.control,
            "enabled": "true",
        },
        headers=keeper.h,
    )
    made = [_backup(site)]
    for _ in range(2):
        time.sleep(1.05)  # an archive's name is its second
        made.append(_backup(site))
    keeper.post("/admin/keeper/sites/1/fetch", headers=keeper.h)
    _until(lambda: not copies.running(1))
    folder = keeper.base / "satul-mare"  # the site's name, made a folder's
    kept = sorted(p.name for p in folder.glob("*.tar.gz"))
    assert kept == sorted(made)[-2:]  # backup_keep: 2, the newest
    for name in kept:
        said = (folder / f"{name}.sha256").read_text().split()[0]
        assert said == hashlib.sha256((folder / name).read_bytes()).hexdigest()
    page = keeper.get("/admin/keeper/sites/1").text
    assert kept[-1] in page and "Last copied" in page and "control token is needed" not in page
    # a copy already there is not downloaded again
    before = (folder / kept[-1]).stat().st_mtime_ns
    copies.fetch(keeper.app.state.nest.bindings.get("nest.db"), _seal(keeper), 1, keeper.base, 2)
    assert (folder / kept[-1]).stat().st_mtime_ns == before
    assert "keeper.fetch" in page  # in the actions' log, with who asked


def _seal(c):
    return c.app.state.nest.module_state["keeper"]["seal"]


def test_a_download_is_kept_only_whole_and_right(tmp_path):
    body = b"an archive" * 1000

    class Serve(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            assert self.headers["Authorization"] == "Bearer na_x"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Serve)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/x"
    good = hashlib.sha256(body).hexdigest()
    try:
        dest = tmp_path / "s-20260101-000000.tar.gz"
        assert "SHA-256" in sites.download(url, "na_x", dest, size=len(body), sha256="0" * 64)
        assert not dest.exists() and not list(tmp_path.iterdir())  # nothing half-kept
        assert sites.download(url, "na_x", dest, size=len(body) - 1, sha256=good)
        assert not list(tmp_path.iterdir())
        assert sites.download(url, "na_x", dest, size=len(body), sha256=good) == ""
        assert dest.read_bytes() == body
    finally:
        server.shutdown()


def test_a_ticket_is_good_once(tmp_path):
    archive = tmp_path / "s-20260101-000000.tar.gz"
    archive.write_bytes(b"x")
    t = copies.ticket(archive, "0" * 64)
    assert copies.redeem(t) == archive
    assert copies.redeem(t) is None and copies.redeem("nope") is None


# --- the host helper's restores -----------------------------------------------------------------


@pytest.fixture
def restorer(tmp_path, monkeypatch):
    """A host helper that allows restores, its site's data folder, a stand-in nest-site."""
    nh = load_helper()
    etc, state, data = tmp_path / "etc", tmp_path / "state", tmp_path / "data" / "gari"
    etc.mkdir()
    (data / "backups").mkdir(parents=True)
    token = "nh_" + "y" * 43
    keeper_url = tmp_path / "keeper-url"  # set by a test that serves the keeper's copies
    keeper_url.write_text("")

    def config():
        (etc / "host.conf").write_text(
            f"TOKEN_SHA256={nh.kept(token)}\nBIND=127.0.0.1\nPORT=0\n"
            f"ALLOW=restart restore\nKEEPER_URL={keeper_url.read_text()}\n"
        )
        nh.Handler.config = nh.Config(str(etc))

    (etc / "gari.conf").write_text(f"PORT=8400\nDATA={data}\n")
    fake = tmp_path / "nest-site"
    fake.write_text('#!/bin/sh\necho "nest-site $1 $2 $3"\n')
    fake.chmod(0o755)
    monkeypatch.setattr(nh, "NEST_SITE", str(fake))
    monkeypatch.setattr(nh, "STATE", str(state))
    monkeypatch.setattr(nh, "_out", lambda command, timeout=10: (0, "active\n"))
    config()
    nh.Handler.jobs, nh.Handler.failures = nh.Jobs(), {}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), nh.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield nh, base, token, data, (keeper_url, config)
    server.shutdown()


def post_json(url, token, body):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_restore_is_not_allowed_unless_named(tmp_path):
    nh = load_helper()
    (tmp_path / "host.conf").write_text(f"TOKEN_SHA256={nh.kept('nh_a')}\n")
    assert "restore" not in nh.Config(str(tmp_path)).allow  # the default ALLOW leaves it out
    (tmp_path / "host.conf").write_text(f"TOKEN_SHA256={nh.kept('nh_a')}\nKEEPER_URL=ftp://x\n")
    with pytest.raises(SystemExit):
        nh.Config(str(tmp_path))


def test_the_helper_restores_an_archive_of_the_server(restorer):
    _nh, base, token, data, _keeper = restorer
    name = "gari-20261126-033012.tar.gz"
    (data / "backups" / name).write_bytes(b"archive")
    (data / "backups" / "gari-20261126-040000.partial").write_bytes(b"half")
    code, listed = ask(f"{base}/v1/sites/gari/backups", token)
    assert code == 200 and [b["name"] for b in listed["backups"]] == [name]
    url = f"{base}/v1/sites/gari/restore"
    assert post_json(url, token, {"archive": "../../etc/passwd"})[0] == 400
    assert post_json(url, token, {"archive": "gari-20200101-000000.tar.gz"})[0] == 404
    assert post_json(url, token, {})[0] == 400
    assert ask(url, token, "POST")[0] == 400  # no body: which archive?
    code, job = post_json(url, token, {"archive": name})
    assert code == 202 and job["archive"] == name
    done = wait(base, token, job["id"])
    assert done["code"] == 0 and f"nest-site restore gari {data}/backups/{name}" in done["output"]


def test_the_helper_restores_the_keepers_copy_only_if_its_sha256_is_right(restorer, tmp_path):
    _nh, base, token, data, (keeper_url, config) = restorer
    body = b"the keeper's copy" * 500
    served = []

    class Keeper(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            served.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Keeper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"{base}/v1/sites/gari/restore"
    name = "gari-20261126-033012.tar.gz"
    ticket = "t" * 43
    try:
        asked = {"archive": name, "ticket": ticket, "sha256": hashlib.sha256(body).hexdigest()}
        assert post_json(url, token, asked)[0] == 409  # no KEEPER_URL yet
        keeper_url.write_text(f"http://127.0.0.1:{server.server_address[1]}/k")
        config()
        assert post_json(url, token, {**asked, "ticket": "bad ticket!"})[0] == 400
        assert post_json(url, token, {**asked, "sha256": "x"})[0] == 400
        code, job = post_json(url, token, {**asked, "sha256": "0" * 64})
        done = wait(base, token, job["id"])
        assert done["code"] == 1 and "nothing replaced" in done["output"]
        assert "nest-site restore" not in done["output"] and not (data / "backups" / name).exists()
        code, job = post_json(url, token, asked)
        done = wait(base, token, job["id"])
        assert done["code"] == 0 and "SHA-256 checked" in done["output"], done["output"]
        assert (data / "backups" / name).read_bytes() == body
        assert served[-1] == f"/k/backups/fetch/{ticket}"
    finally:
        server.shutdown()


# --- the keeper, its servers, a restore end to end ------------------------------------------------


def test_the_keeper_restores_its_copy_on_another_server(restorer, tmp_path, monkeypatch):
    _nh, base, token, data, (keeper_url, config) = restorer
    seen_headers = []
    real_call = sites.call

    def call(url, tok, path, **kw):
        if url == base:
            seen_headers.append(kw.get("headers") or {})
            return real_call(url, tok, path, **kw)
        status = {"ok": True, "app": {"name": "gari", "version": "1"}, "scope": "control"}
        return sites.Answer(True, 200, status, 3)

    monkeypatch.setattr(sites, "call", call)
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(KEEPER, encoding="utf-8")
    env = {
        "NEST_APP_WORKSPACE": str(tmp_path / "kws"),
        "NEST_KEEPER__KEEPER__BACKUP_DIR": str(tmp_path / "copies"),
    }
    app = create_app(root, environ=env)
    with TestClient(app) as c:
        _sign_in(c, app)
        # the keeper's own address, as the other server's helper reaches it (its tunnel)
        proxy = _proxy(c)
        keeper_url.write_text(proxy[0])
        config()
        bad = c.post(
            "/admin/keeper/servers/new",
            data={"name": "server-2", "url": "http://host-2.example:8090", "token": token},
            headers=c.h,
        )
        assert bad.status_code == 400  # plain http only near
        assert (
            c.post(
                "/admin/keeper/servers/new",
                data={"name": "server-2", "url": base, "token": token, "access_id": "a.access"},
                headers=c.h,
            ).status_code
            == 400
        )  # Access: both halves or neither
        c.post(
            "/admin/keeper/servers/new",
            data={
                "name": "server-2",
                "url": base,
                "token": token,
                "access_id": "abc.access",
                "access_secret": "s3cret",
            },
            headers=c.h,
        )
        servers_page = c.get("/admin/keeper/servers").text
        assert "server-2" in servers_page and "gari" in servers_page and "restore" in servers_page
        assert token not in servers_page and "s3cret" not in servers_page
        assert seen_headers[-1] == {
            "CF-Access-Client-Id": "abc.access",
            "CF-Access-Client-Secret": "s3cret",
        }
        c.post(
            "/admin/keeper/sites/new",
            data={
                "name": "Gări",
                "url": "https://gari.example",
                "token": "na_x",
                "host_site": "gari",
                "server_id": "1",
            },
            headers=c.h,
        )
        page = c.get("/admin/keeper/sites/1").text
        assert "server-2" in page and "Restore…" in page
        # the keeper's copy of a backup
        db = app.state.nest.bindings.get("nest.db")
        with db.session() as s, s.begin():
            from nest_keeper.models import KeeperSite

            s.get(KeeperSite, 1).backup_folder = "gari"
        name = "gari-20261126-033012.tar.gz"
        (tmp_path / "copies" / "gari").mkdir(parents=True)
        body = b"kept at the keeper" * 300
        (tmp_path / "copies" / "gari" / name).write_bytes(body)
        form = c.get("/admin/keeper/sites/1/server/restore").text
        assert f"keeper:{name}" in form
        wrong = c.post(
            "/admin/keeper/sites/1/server/restore",
            data={"source": f"keeper:{name}", "confirm": "gary"},
            headers=c.h,
        )
        assert wrong.status_code == 400
        r = c.post(
            "/admin/keeper/sites/1/server/restore",
            data={"source": f"keeper:{name}", "confirm": "gari"},
            headers=c.h,
            follow_redirects=False,
        )
        assert r.status_code == 303 and "/server/jobs/" in r.headers["location"], r.text
        done = wait(base, token, r.headers["location"].rsplit("/", 1)[1])
        assert done["code"] == 0, done["output"]
        assert (data / "backups" / name).read_bytes() == body
        assert f"nest-site restore gari {data}/backups/{name}" in done["output"]
        assert proxy[1] == [404] or proxy[1][-1] == 200
        # the ticket was good once
        ticket_path = proxy[2][-1]
        assert c.get(ticket_path).status_code == 404
        assert "server.restore" in c.get("/admin/keeper/sites/1").text
        # its token sealed with another key (the keeper's changed): the page says which server
        from nest_keeper.models import KeeperServer

        with db.session() as s, s.begin():
            s.get(KeeperServer, 1).token = sites.seal("another key", token)
        page = c.get("/admin/keeper/sites/1").text
        assert "token of its server cannot be read" in page and "/servers/1/edit" in page
        assert "No host helper yet" not in page
        # forgetting the server keeps the site, with no helper of its own
        c.post("/admin/keeper/servers/1/delete", headers=c.h)
        assert host.servers(db, _seal(c)) == []
        proxy[3].shutdown()


def _proxy(c):
    """A real address in front of the keeper's test client (as its tunnel would be)."""
    codes, paths = [], []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            paths.append(self.path)
            r = c.get(self.path)
            codes.append(r.status_code)
            self.send_response(r.status_code)
            self.send_header("Content-Length", str(len(r.content)))
            self.end_headers()
            self.wfile.write(r.content)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", codes, paths, server
