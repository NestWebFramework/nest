"""The admin panel's modules page: core modules locked, the others disabled, enabled,
uninstalled or added from it; each change logged, and applied to the running site."""

import textwrap
import time

import pytest
from fastapi.testclient import TestClient
from test_auth import PASSWORD, client_for, post
from test_composition import APP

from nest import create_app
from nest.host import Reloadable
from nest.modules import history


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP) + "  nest.search: {providers: [search-sqlite]}\n", encoding="utf-8"
    )
    return root


def register(c):
    """The first account, at this site's /cont: the administrator."""
    r = post(c, "/cont/register", email="ana@example.ro", name="Ana", password=PASSWORD)
    assert r.status_code in (200, 303), r.text


def admin_client(site, tmp_path):
    c = client_for(site, tmp_path / "ws")
    c.__enter__()
    register(c)  # the first account is the administrator
    return c


def test_the_page_shows_what_is_locked_and_what_may_change(site, tmp_path):
    c = admin_client(site, tmp_path)
    page = c.get("/admin/modules")
    assert page.status_code == 200
    text = page.text
    assert 'id="m-auth"' in text and "badge lock" in text  # core: no actions
    auth_card = text.split('id="m-auth"')[1].split("</li>")[0]
    assert "/disable" not in auth_card and "/uninstall" not in auth_card
    forum_card = text.split('id="m-forum"')[1].split("</li>")[0]
    assert "/modules/forum/disable" in forum_card and "/modules/forum/uninstall" in forum_card
    redirects = text.split('id="m-redirects"')[1].split("</li>")[0]
    assert "/modules/redirects/enable" in redirects  # listed, off
    assert 'href="/admin/modules"' in c.get("/admin/").text  # in the panel's menu


def test_disable_from_the_panel_is_logged_and_applies_on_restart(site, tmp_path):
    c = admin_client(site, tmp_path)
    r = post(c, "/admin/modules/forum/disable")
    assert r.status_code == 200
    assert "forum is disabled; its data is kept." in r.text
    assert "It applies when the site is restarted." in r.text  # no reloader in this test
    assert "Waiting for the site to restart: forum." in r.text
    log = history(tmp_path / "ws")
    assert log[0]["disable"] == ["forum"] and log[0]["outcome"] == "done"
    assert log[0]["who"] == "ana@example.ro"
    with TestClient(
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    ) as fresh:
        assert fresh.get("/forum/").status_code == 404


def test_refusals_are_shown_and_logged(site, tmp_path):
    c = admin_client(site, tmp_path)
    r = post(c, "/admin/modules/auth/disable")
    assert r.status_code == 400 and "auth is a core module" in r.text
    r = post(c, "/admin/modules/forum/uninstall", confirm="nope")
    assert r.status_code == 400 and "Type the module&#39;s name, forum" in r.text
    assert history(tmp_path / "ws")[0]["outcome"] == "refused"


def test_only_administrators_reach_it(site, tmp_path):
    c = admin_client(site, tmp_path)
    post(c, "/cont/logout")
    assert c.get("/admin/modules", follow_redirects=False).status_code in (303, 401, 403)


def test_under_nest_run_the_site_is_made_again_in_place(site, tmp_path, monkeypatch):
    monkeypatch.setenv("NEST_APP_WORKSPACE", str(tmp_path / "ws"))
    app = Reloadable(lambda: create_app(site))
    with TestClient(app) as c:
        c.get("/healthz")
        register(c)
        assert c.get("/forum/").status_code == 200
        r = post(c, "/admin/modules/forum/disable")
        assert "The site is reloading to apply it." in r.text
        for _ in range(50):  # made again a moment after the answer
            time.sleep(0.1)
            if c.get("/forum/").status_code == 404:
                break
        assert c.get("/forum/").status_code == 404
        assert c.get("/healthz").status_code == 200
        r = post(c, "/admin/modules/forum/enable")
        for _ in range(50):
            time.sleep(0.1)
            if c.get("/forum/").status_code == 200:
                break
        assert c.get("/forum/").status_code == 200
