"""The site's language and the admin panel's: chosen apart, each from its own list."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user

from nest import create_app
from nest.i18n import Catalogs

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro, en], admin_languages: [ro, en, hu], browser_language: false}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        db = app.state.nest.bindings.get("nest.db")
        create_user(db, "ed@example.ro", PASSWORD, roles=("editor",))
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ed@example.ro",
                "password": PASSWORD,
            },
        )
        yield c


def choose(c, language, scope="", next_="/"):
    data = {"csrf_token": c.cookies["nest_csrf"], "language": language, "next": next_}
    if scope:
        data["scope"] = scope
    return c.post("/_nest/language", data=data, follow_redirects=False)


def test_negotiation_keeps_to_the_languages_offered():
    cats = Catalogs(["ro", "en", "hu"], "ro")
    assert cats.negotiate("hu", None, ["ro", "en"]) == "ro"  # not the site's: the default
    assert cats.negotiate(None, "hu-HU,en;q=0.8", ["ro", "en"]) == "en"
    assert cats.negotiate("hu", None, ["ro", "en", "hu"]) == "hu"


def test_the_site_and_the_admin_panel_each_keep_their_language(site):
    assert (
        'lang="ro"' in site.get("/", headers={"accept-language": "en-US,en"}).text
    )  # the site's default, not the browser's
    assert (
        '<html lang="en">' in site.get("/admin/", headers={"accept-language": "en-US,en"}).text
    )  # the panel: the browser's
    choose(site, "en")
    assert '<html lang="en">' in site.get("/").text
    assert '<html lang="en">' in site.get("/admin/").text  # no admin choice yet: the site's
    r = choose(site, "ro", scope="admin", next_="/admin/")
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    admin = site.get("/admin/").text
    assert '<html lang="ro">' in admin and "Administrare" in admin
    assert '<html lang="en">' in site.get("/").text  # the site stays as its reader chose
    assert "scope=admin" in admin and ">Magyar<" in admin  # the panel's own list
    choose(site, "hu")  # not a site language: refused
    assert '<html lang="en">' in site.get("/").text
    choose(site, "hu", scope="admin")
    assert '<html lang="hu">' in site.get("/admin/").text


def test_the_switch_shows_only_where_there_is_a_choice(site):
    page = site.get("/").text
    head = page.split("</header>")[0]
    assert 'href="/_nest/language?language=en&amp;next=/"' in head and "scope=admin" not in head
    r = site.get("/_nest/language?language=en&next=/category/x/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/category/x/"
    assert "nest_locale=en" in r.headers["set-cookie"]
    away = site.get(
        "/_nest/language?language=en&next=https://evil.example/", follow_redirects=False
    )
    assert away.headers["location"] == "/"  # only a path on this site


def test_a_readers_page_gives_no_cookie_and_may_be_cached(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as reader:
        home = reader.get("/")
        assert "set-cookie" not in home.headers  # no form on it: no token, no cookie
        assert home.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=300"
        assert "Cookie" in home.headers["vary"] and "X-CSRF-Token" not in home.text
        login = reader.get("/cont/login")  # a form: its token, its cookie, not cached
        assert "nest_csrf=" in login.headers["set-cookie"] and "public" not in login.headers.get(
            "cache-control", ""
        )

        db = app.state.nest.bindings.get("nest.db")
        create_user(db, "ed@example.ro", PASSWORD, roles=("editor",))
        reader.post(
            "/cont/login",
            data={
                "csrf_token": reader.cookies["nest_csrf"],
                "email": "ed@example.ro",
                "password": PASSWORD,
            },
        )
        signed = reader.get("/")
        assert (
            "public" not in signed.headers.get("cache-control", "")
            and "X-CSRF-Token" in signed.text
        )  # a member's page is theirs
