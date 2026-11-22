"""Secrets set in the admin panel (API keys, clients' secrets): kept encrypted in the
workspace's settings file, under a key from the application's secret key; never shown
again; the environment still wins."""

import textwrap

from fastapi.testclient import TestClient
from nest_auth.sessions import create_user

from nest import create_app
from nest.manifest import SettingSpec
from nest.settings import SettingsError, SettingsStore

APP = """
module: {name: go, id: test.app.go, type: application, version: 0.1.0}
application: {title: Drum, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: planner, route: /incotro}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def store(tmp_path, environ=None, secret="the site's key"):
    s = SettingsStore(tmp_path / "settings.conf", "go", environ or {}, secret=secret)
    s.declare(
        "flights",
        {
            "radar_key": SettingSpec(type="str", secret=True),
            "every": SettingSpec(type="int", default=20),
        },
    )
    return s


def test_a_secret_is_kept_encrypted_and_read_back(tmp_path):
    s = store(tmp_path)
    s.set("flights.radar_key", "abc-123-SECRET")
    assert (
        s.get("flights.radar_key") == "abc-123-SECRET" and s.source("flights.radar_key") == "store"
    )
    on_disk = (tmp_path / "settings.conf").read_text()
    assert "abc-123" not in on_disk and "flights.radar_key=enc:" in on_disk
    assert store(tmp_path).get("flights.radar_key") == "abc-123-SECRET"  # another process
    assert store(tmp_path, secret="another key").get("flights.radar_key") is None  # not ours
    s.set("flights.radar_key", "")  # emptied: gone
    assert (
        s.get("flights.radar_key") is None
        and "radar_key" not in (tmp_path / "settings.conf").read_text()
    )


def test_the_environment_still_wins(tmp_path):
    s = store(tmp_path, {"NEST_GO__FLIGHTS__RADAR_KEY": "from-env"})
    assert s.get("flights.radar_key") == "from-env"
    try:
        s.set("flights.radar_key", "x")
        raise AssertionError("set over the environment")
    except SettingsError:
        pass


def test_the_admin_sets_a_secret_without_ever_showing_it(tmp_path):
    root = tmp_path / "go"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        db = app.state.nest.bindings.get("nest.db")
        create_user(db, "ana@example.ro", "correct horse battery", roles=("admin",))
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ana@example.ro",
                "password": "correct horse battery",
            },
        )
        page = c.get("/admin/settings/planner").text
        assert 'name="planner.vault_key" type="password"' in page and "nesetată" in page
        settings = app.state.nest.settings
        form = {  # the whole form, as a browser sends it
            key: settings.get(key)
            for key, owner, _n, spec in settings.specs()
            if owner == "planner" and not spec.secret
        }

        def send(**extra):
            return c.post(
                "/admin/settings/planner",
                data={"csrf_token": c.cookies["nest_csrf"], **form, **extra},
            )

        send(**{"planner.vault_key": "shared-across-four-sites"})
        assert app.state.nest.settings.get("planner.vault_key") == "shared-across-four-sites"
        page = c.get("/admin/settings/planner").text
        assert "shared-across-four-sites" not in page and "păstrat criptat" in page
        send()  # left empty: kept
        assert app.state.nest.settings.get("planner.vault_key") == "shared-across-four-sites"
        send(**{"reset:planner.vault_key": "1"})
        assert app.state.nest.settings.get("planner.vault_key") is None


def test_the_memory_cache_keeps_to_its_megabytes():
    import asyncio

    from nest_cache_memory import MemoryCache

    cache = MemoryCache(max_items=100000, max_mb=0.1)
    for i in range(500):
        asyncio.run(cache.set(f"k{i}", "x" * 1000))
    assert cache.used_bytes <= 0.1 * 1024 * 1024
    assert asyncio.run(cache.get("k499")) and asyncio.run(cache.get("k0")) is None
