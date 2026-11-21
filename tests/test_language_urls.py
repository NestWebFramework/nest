"""An address per language (application.language_urls: prefix): the default at /, others
under /en/...; links, redirects and hreflang follow; the site's languages chosen in the
admin panel, kept in the workspace."""

import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from test_admin_modules import register
from test_auth import client_for, post

from nest import create_app
from nest.composition import load_languages

APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base, languages: [ro, en], language_urls: prefix, browser_language: false}
modules:
  - {name: auth, route: /cont, core: true}
  - {name: admin, route: /admin, core: true}
  - {name: forum, route: /forum}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    return root


def client(site, tmp_path):
    return TestClient(
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}),
        follow_redirects=False,
    )


def test_the_default_is_at_the_root_and_the_others_under_their_prefix(site, tmp_path):
    with client(site, tmp_path) as c:
        ro, en = c.get("/forum/"), c.get("/en/forum/")
        assert ro.status_code == en.status_code == 200
        assert '<html lang="ro"' in ro.text and '<html lang="en"' in en.text
        assert c.get("/en").headers["location"] == "/en/"
        assert c.get("/ro/forum/?page=2").headers["location"] == "/forum/?page=2"  # one address
        assert c.get("/en/admin/").headers["location"] == "/admin/"  # the panel has one
        assert c.get("/en/assets/base/nest.css").headers["location"] == "/assets/base/nest.css"
        assert c.get("/de/forum/").status_code == 404  # not a language of the site


def test_an_english_pages_links_stay_in_english(site, tmp_path):
    with client(site, tmp_path) as c:
        page = c.get("/en/forum/").text
        hrefs = set(re.findall(r'href="([^"]+)"', page))
        assert any(h.startswith("/en/forum") or h.startswith("/en/cont/") for h in hrefs)
        assert not any(h.startswith("/en/assets/") for h in hrefs)
        assert any(h.startswith("/assets/") for h in hrefs)  # files keep their one address
        assert all(not h.startswith("/en/_nest/") for h in hrefs)  # nor Nest's own
        ro_page = c.get("/forum/").text
        assert not re.search(r'href="/en/', ro_page.split("hreflang")[0])  # the default's stay put
        # a redirect from an English page lands in English
        r = c.get("/en/cont/account")
        assert r.status_code in (303, 307) and r.headers["location"].startswith("/en/cont/login")


def test_every_page_says_where_it_is_in_each_language(site, tmp_path):
    with client(site, tmp_path) as c:
        page = c.get("/en/forum/").text
        alternates = dict(
            re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', page)
        )
        assert alternates["ro"].endswith("/forum/") and alternates["en"].endswith("/en/forum/")
        assert alternates["x-default"] == alternates["ro"]


def test_the_language_switch_stays_on_the_page(site, tmp_path):
    with client(site, tmp_path) as c:
        assert c.get("/_nest/language?language=en&next=/forum/").headers["location"] == "/en/forum/"
        assert c.get("/_nest/language?language=ro&next=/forum/").headers["location"] == "/forum/"
        assert (
            "set-cookie" not in c.get("/_nest/language?language=en&next=/").headers
        )  # the address says it


def test_without_prefix_mode_nothing_changes(site, tmp_path):
    (site / "module.yml").write_text(
        textwrap.dedent(APP).replace(", language_urls: prefix", ""), encoding="utf-8"
    )
    with client(site, tmp_path) as c:
        assert c.get("/en/forum/").status_code == 404
        assert "set-cookie" in c.get("/_nest/language?language=en&next=/").headers


def test_the_site_languages_are_chosen_in_the_admin_panel(site, tmp_path):
    c = client_for(site, tmp_path / "ws")
    c.__enter__()
    register(c)
    page = c.get("/admin/languages")
    assert page.status_code == 200 and "Română" in page.text and "/en/" in page.text
    assert post(c, "/admin/languages", action="add", code="Hungarian!").status_code == 400
    assert post(c, "/admin/languages", action="remove", code="ro").status_code == 400  # the default
    assert post(c, "/admin/languages", action="add", code="hu").status_code == 200
    assert load_languages(tmp_path / "ws") == (["ro", "en", "hu"], "ro")
    fresh = TestClient(
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}),
        follow_redirects=False,
    )
    with fresh:
        assert '<html lang="hu"' in fresh.get("/hu/forum/").text  # no table changed
    post(c, "/admin/languages", action="remove", code="hu")
    assert load_languages(tmp_path / "ws") == (["ro", "en"], "ro")
