"""The hello application, end to end, through HTTP."""

import hashlib
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from nest import create_app
from nest.host import HostError
from nest.scaffold import new_app

ROOT = Path(__file__).resolve().parents[1]
HELLO = ROOT / "applications" / "hello"


@pytest.fixture
def client(tmp_path):
    app = create_app(HELLO, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def token_of(page: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def test_home_page_renders_with_safe_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Bună ziua" in r.text
    import yaml

    htmx = yaml.safe_load(
        (Path(__file__).parents[1] / "modules/htmx/src/nest_htmx/module.yml").read_text()
    )["module"]["version"]
    assert f"/assets/htmx/htmx.min.js?v={htmx}" in r.text  # versioned, so caches keep it
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe" not in csp
    assert r.headers["x-frame-options"] == "DENY"
    cookie = r.headers["set-cookie"]
    assert "nest_csrf=" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_assets_are_served(client):
    r = client.get("/assets/base/nest.css")
    assert r.status_code == 200 and "--accent" in r.text
    assert client.get("/assets/htmx/htmx.min.js").status_code == 200


def test_a_post_without_csrf_token_is_refused(client):
    client.get("/")
    r = client.post("/count")
    assert r.status_code == 403


def test_htmx_post_gets_a_fragment(client):
    token = token_of(client.get("/").text)
    r = client.post("/count", headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert r.status_code == 200
    assert r.text.startswith('<p id="counter">') and "<html" not in r.text
    assert "<strong>1</strong>" in r.text


def test_plain_form_post_gets_the_page(client):
    token = token_of(client.get("/").text)
    r = client.post("/count", data={"csrf_token": token})
    assert r.status_code == 200 and "<html" in r.text and "<strong>1</strong>" in r.text


def test_cross_origin_post_is_refused(client):
    token = token_of(client.get("/").text)
    r = client.post("/count", headers={"X-CSRF-Token": token, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_a_forged_cookie_is_not_trusted(client):
    client.cookies.set("nest_csrf", "attacker.chosen")
    r = client.post("/count", headers={"X-CSRF-Token": "attacker.chosen"})
    assert r.status_code == 403


def test_health_and_events(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    detail = client.get("/_nest/health").json()
    assert {m["name"]: m["state"] for m in detail["modules"]}["home"] == "ready"
    assert detail["bindings"] == {"nest.db": ["db-sqlite"], "nest.cache": ["cache-memory"]}
    assert detail["checks"] == {"db-sqlite": True}
    assert client.get("/_nest/events?topic=secret").status_code == 404
    assert client.get("/_nest/events").status_code == 400


def test_runtime_setting_comes_from_the_environment(tmp_path):
    app = create_app(
        HELLO,
        environ={"NEST_APP_WORKSPACE": str(tmp_path), "NEST_HELLO__HOME__GREETING": "Salut"},
    )
    with TestClient(app) as c:
        assert "Salut" in c.get("/").text


def test_production_requires_a_secret_key(tmp_path):
    with pytest.raises(Exception, match="NEST_SECRET_KEY must be set"):
        create_app(HELLO, environ={"NEST_APP_WORKSPACE": str(tmp_path), "NEST_ENV": "production"})


def test_production_hides_docs_and_sets_secure_cookies(tmp_path):
    app = create_app(
        HELLO,
        environ={
            "NEST_APP_WORKSPACE": str(tmp_path),
            "NEST_ENV": "production",
            "NEST_SECRET_KEY": "k" * 40,
            "NEST_MIGRATE": "auto",  # production defaults to check; this test migrates on purpose,
        },
    )
    with TestClient(app, base_url="https://testserver") as c:
        r = c.get("/")
        assert "Secure" in r.headers["set-cookie"]
        assert "strict-transport-security" in r.headers
        assert c.get("/_nest/docs").status_code == 404


def test_a_module_using_an_undeclared_facility_stops_the_start(tmp_path):
    app_root = new_app("probe", tmp_path)
    init = app_root / "modules" / "home" / "home" / "__init__.py"
    init.write_text(
        init.read_text().replace("host.mount(router)", "host.mount(router)\n    host.workspace")
    )
    with pytest.raises(HostError, match="add it to requires.host"):
        create_app(app_root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def test_a_scaffolded_app_runs(tmp_path):
    app_root = new_app("fresh", tmp_path)
    with TestClient(
        create_app(app_root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    ) as c:
        r = c.get("/")
        assert r.status_code == 200 and "It runs." in r.text


def test_vendored_htmx_matches_its_recorded_sums():
    root = ROOT / "modules" / "htmx" / "src" / "nest_htmx"  # the manifest's paths start here
    manifest = yaml.safe_load((root / "module.yml").read_text())  # it travels in the package
    for item in manifest["vendored"]:
        digest = hashlib.sha256((root / item["file"]).read_bytes()).hexdigest()
        assert digest == item["sha256"], item["file"]


def test_two_apps_with_the_same_local_module_id_each_get_their_own_code(tmp_path):
    texts = {}
    for folder in ("one", "two"):
        root = new_app("twin", tmp_path / folder)
        page = root / "modules" / "home" / "templates" / "index.html"
        init = root / "modules" / "home" / "home" / "__init__.py"
        init.write_text(
            init.read_text().replace('"home/index.html")', f'"home/index.html", who="{folder}")')
        )
        page.write_text(page.read_text().replace("It runs.", "{{ who }}"))
        app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / folder / "ws")})
        with TestClient(app) as c:
            texts[folder] = c.get("/").text
    assert "<p>one</p>" in texts["one"] and "<p>two</p>" in texts["two"]


def test_an_application_serves_its_own_files(tmp_path):
    """An application's static/ folder (a client it builds) is served at /assets/<app>,
    and asset() gives it a version that changes with its files."""
    import shutil  # noqa: PLC0415

    site = tmp_path / "hello"
    shutil.copytree(HELLO, site)
    (site / "static" / "play").mkdir(parents=True)
    (site / "static" / "play" / "play.js").write_text("console.log('joc')", encoding="utf-8")
    (site / "templates").mkdir(exist_ok=True)
    app = create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        assert c.get("/assets/hello/play/play.js").text == "console.log('joc')"
        url = app.state.nest.asset("hello", "play/play.js")
        assert url.startswith("/assets/hello/play/play.js?v=") and "-" in url.split("v=")[1]


def test_the_event_stream_knows_who_is_asking():
    """A topic may be the signed-in user's own: the event stream resolves the session."""
    from nest_auth.web import SKIP_PREFIXES  # noqa: PLC0415

    assert not "/_nest/events".startswith(SKIP_PREFIXES)
    assert "/_nest/language".startswith(SKIP_PREFIXES) and "/assets/x".startswith(SKIP_PREFIXES)
