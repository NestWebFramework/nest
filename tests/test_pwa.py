"""The web app (the pwa module): a manifest with the theme's icons and menu, a service
worker that keeps only public pages and leaves the admin and account pages alone, an
offline page, the install and update notices on every page, the Android app links once
set, and one address for each of them whatever the visitor's language."""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_pwa import core

from nest import create_app

APP = """
module: {{name: site, id: test.app.site, type: application, version: 0.1.0, description: Coaches between towns.}}
application:
  title: Transportul.ro
  port: 8000
  theme: {theme}
  languages: [ro, en]
  language_urls: prefix
  theme_settings:
    transit-lines:
      variant: road
      menu: "Coaches = /; Towns = /orase; Stations = /autogari; Europe = /europa; More = /mai"
modules:
  - {{name: pwa, config: {config}}}
  - {{name: consent, route: /cookies}}
  - {{name: auth, route: /cont}}
  - {{name: admin, route: /admin}}
bind:
  nest.db: {{providers: [db-sqlite]}}
"""


def make(tmp_path, theme="transit-lines", config="{}"):
    root = tmp_path / "site"
    root.mkdir(parents=True)
    (root / "module.yml").write_text(
        textwrap.dedent(APP.format(theme=theme, config=config)), encoding="utf-8"
    )
    return TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}))


@pytest.fixture
def site(tmp_path):
    with make(tmp_path) as c:
        yield c


def test_the_manifest_has_the_themes_icons_colour_and_menu(site):
    r = site.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith(
        "application/manifest+json"
    )
    m = r.json()
    assert (m["name"], m["short_name"], m["start_url"], m["scope"], m["display"]) == (
        "Transportul.ro",
        "Transportul",
        "/",
        "/",
        "standalone",
    )
    assert m["theme_color"] == "#c2410c"  # the road variant's colour
    sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    assert all("icon-road" in i["src"] for i in m["icons"])
    assert (
        site.get(next(i["src"] for i in m["icons"] if i["purpose"] == "maskable")).status_code
        == 200
    )
    assert [s["url"] for s in m["shortcuts"]] == ["/", "/orase", "/autogari", "/europa"]  # four
    assert m["description"] == "Coaches between towns." and m["lang"] == "ro"


def test_a_theme_without_icons_gets_the_modules_own(tmp_path):
    with make(tmp_path, theme="base") as c:
        m = c.get("/manifest.webmanifest").json()
        assert all("/assets/pwa/" in i["src"] for i in m["icons"]) and m["theme_color"] == "#12355b"


def test_the_service_worker_keeps_only_what_it_may(site):
    r = site.get("/sw.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache" and r.headers["service-worker-allowed"] == "/"
    script = r.text
    config = json.loads(script.split("const CONFIG = ", 1)[1].split(";\n", 1)[0])
    assert config["offline"] == "/offline" and "/offline" in config["precache"]
    assert any(u.startswith("/assets/") for u in config["precache"])  # the site's look
    assert {"/admin", "/cont", "/_nest"} <= set(config["never"])  # never the admin or accounts
    assert '!cc.includes("private")' in script  # never a page made for a signed-in visitor
    assert "__VERSION__" not in script and "__CONFIG__" not in script
    assert site.get("/sw.js").text == script  # the same version until something changes


def test_the_version_changes_with_what_it_keeps(tmp_path):
    with make(tmp_path, config="{offline_pages: 10}") as c:
        ten = c.get("/sw.js").text
    with make(tmp_path / "b", config="{offline_pages: 20}") as c:
        twenty = c.get("/sw.js").text
    version = lambda s: s.split('const VERSION = "', 1)[1][:12]  # noqa: E731
    assert version(ten) != version(twenty)


def test_every_page_says_it_is_an_app_and_the_admin_does_not(site):
    page = site.get("/cookies/").text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in page
    assert '<meta name="theme-color" content="#c2410c">' in page
    assert (
        'id="nest-pwa"' in page and "/assets/pwa/pwa.js" in page and "Instalează aplicația" in page
    )
    en = site.get("/en/cookies/").text
    assert 'href="/manifest.webmanifest"' in en and 'href="/en/manifest.webmanifest"' not in en
    assert "Install the app" in en


def test_a_signed_in_visitors_pages_are_private(site):
    from nest_auth.sessions import create_user

    db = site.app.state.nest.bindings.get("nest.db")
    create_user(db, "a@example.com", "a long passphrase 42", roles=["admin"])
    anonymous = site.get("/cookies/")
    assert "private" not in anonymous.headers.get("cache-control", "")
    site.get("/cont/login")
    site.post(
        "/cont/login",
        data={
            "email": "a@example.com",
            "password": "a long passphrase 42",
            "csrf_token": site.cookies["nest_csrf"],
        },
    )
    assert site.get("/cookies/").headers["cache-control"] == "private, no-cache"


def test_the_offline_page(site):
    r = site.get("/offline")
    assert r.status_code == 200 and "Nu ești conectat la internet" in r.text
    assert 'data-cache="nest-pages"' in r.text and "noindex" in r.text


def test_one_address_whatever_the_language(site):
    for path in ("/sw.js", "/manifest.webmanifest", "/offline"):
        assert site.get(path, follow_redirects=False).status_code == 200
    assert site.get("/en/sw.js", follow_redirects=False).status_code in (301, 307, 308, 404)


def test_the_android_app_links_once_set(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/.well-known/assetlinks.json").status_code == 404
    fp = ":".join(["AB"] * 32)
    config = "{android_package: ro.transportul.app, android_fingerprints: '" + fp + " bad'}"
    with make(tmp_path / "b", config=config) as c:
        links = c.get("/.well-known/assetlinks.json").json()
        assert links[0]["target"] == {
            "namespace": "android_app",
            "package_name": "ro.transportul.app",
            "sha256_cert_fingerprints": [fp],  # the malformed one left out
        }


def test_shortcuts_are_local_paths_only():
    assert core.shortcuts("A = /a; B = https://evil.example; C = //x; D=/d", "") == [
        ("A", "/a"),
        ("D", "/d"),
    ]
    assert core.shortcuts("", "M = /m") == [("M", "/m")]
