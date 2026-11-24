"""Running for real: the production check, backups and restores, old folders redirected,
assets kept by caches, and only the site's own hosts answered."""

import tarfile
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_content import service
from nest_content.service import EntryData

from nest import create_app
from nest.ops import RestoreError, backup, check, restore

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: redirects}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
redirect_prefixes:
  /wp-content/uploads/: /media/uploads/
"""

KEY = "k" * 40


def make(tmp_path, **env):
    root = tmp_path / "site"
    root.mkdir(exist_ok=True)
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    return create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws"), **env})


def test_an_old_folder_is_sent_on_with_the_rest_of_its_path(tmp_path):
    with TestClient(make(tmp_path)) as c:
        r = c.get("/wp-content/uploads/2012/12/a.jpg?x=1", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/media/uploads/2012/12/a.jpg?x=1"
        assert c.get("/wp-content/uploads/", follow_redirects=False).status_code == 404


def test_versioned_assets_are_kept_for_a_year(tmp_path):
    with TestClient(make(tmp_path)) as c:
        css = c.get("/assets/content/content.css?v=0.1.0")
        assert css.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert (
            c.get("/assets/content/content.css").headers["cache-control"] == "public, max-age=3600"
        )


def test_only_the_sites_hosts_are_answered(tmp_path):
    app = make(tmp_path, NEST_ALLOWED_HOSTS="satul.ro, www.satul.ro")
    with TestClient(app, base_url="https://satul.ro") as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/healthz", headers={"host": "evil.example.com"}).status_code == 400
        assert c.get("/healthz", headers={"host": "localhost"}).status_code == 200


def test_the_check_names_what_production_lacks(tmp_path):
    with TestClient(make(tmp_path)) as c:
        report = check(c.app.state.nest)
    text = "\n".join(f"{f.level} {f.text}" for f in report.findings)
    assert report.failed
    assert "fail NEST_ENV is not production" in text
    assert "fail NEST_SECRET_KEY" in text
    assert "warn NEST_ALLOWED_HOSTS" in text
    assert "warn no backup yet" in text and "warn 0 administrator" in text
    assert "ok SQLite app.db: journal wal" in text


def test_ready_for_production(tmp_path):
    with TestClient(make(tmp_path)):  # in development it migrates; production asks for it
        pass
    app = make(tmp_path, NEST_ENV="production", NEST_SECRET_KEY=KEY, NEST_ALLOWED_HOSTS="satul.ro")
    with TestClient(app, base_url="https://satul.ro"):
        nest = app.state.nest
        nest.settings.set("content.site_url", "https://satul.ro")
        from nest_auth.sessions import create_user

        create_user(
            nest.bindings.get("nest.db"), "a@satul.ro", "correct horse battery", roles=("admin",)
        )
        backup(nest)
        report = check(nest)
    assert not report.failed, [f.text for f in report.findings if f.level == "fail"]
    assert not [f for f in report.findings if f.level == "warn"]


def test_a_backup_comes_back_whole(tmp_path):
    app = make(tmp_path)
    with TestClient(app) as c:
        nest = app.state.nest
        db, search, storage = (
            nest.bindings.get(k) for k in ("nest.db", "nest.search", "nest.storage")
        )
        types = nest.module_state["content"]["types"]
        service.save_entry(
            db, search, types, EntryData(type="page", title="Istoria", status="published")
        )
        storage.put("uploads/poza.jpg", b"\xff\xd8 poza", "image/jpeg")
        storage.put("_sized/640/uploads/poza.jpg.webp", b"made again", "image/webp")
        (nest.workspace / ".env").write_text("NEST_SECRET_KEY=" + KEY)
        archive = backup(nest, keep=1)
        assert c.get("/istoria/").status_code == 200  # the site ran on while it was taken
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "backup.json" in names and "workspace/data/app.db" in names
    assert "workspace/data/search.db" in names
    assert "workspace/media/uploads/poza.jpg" in names
    assert not [n for n in names if n.endswith(".env") or "_sized" in n or n.endswith("-wal")]

    with pytest.raises(RestoreError, match="already holds data"):
        restore("sat", archive, tmp_path / "ws")
    with pytest.raises(RestoreError, match="not 'other'"):
        restore("other", archive, tmp_path / "elsewhere")
    fresh = tmp_path / "fresh"
    meta = restore("sat", archive, fresh)
    assert meta["application"] == "sat"
    assert (fresh / "media/uploads/poza.jpg").read_bytes() == b"\xff\xd8 poza"
    root = tmp_path / "site"
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(fresh)})) as c:
        assert c.get("/istoria/").status_code == 200


def test_the_machines_own_health_checks_stay_out_of_the_access_log():
    import logging

    from nest.serve import QuietChecks

    quiet = QuietChecks()

    def line(ip, path):
        return logging.LogRecord(
            "uvicorn.access",
            20,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            (ip, "GET", path, "1.1", 200),
            None,
        )

    assert not quiet.filter(line("127.0.0.1:47248", "/healthz"))  # Docker's, every 30 s
    assert quiet.filter(line("5.13.247.38:0", "/healthz"))  # from outside: kept
    assert quiet.filter(line("43.173.1.1:0", "/cfr/"))  # a visitor: kept
