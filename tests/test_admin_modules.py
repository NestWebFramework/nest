"""The admin panel's modules page: core modules locked, the others disabled, enabled,
uninstalled or added from it; each change logged, and applied to the running site."""

import re
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
    auth_card = text.split('id="m-auth"')[1].split("</tr>")[0]
    assert "/disable" not in auth_card and "/uninstall" not in auth_card
    forum_card = text.split('id="m-forum"')[1].split("</tr>")[0]
    assert "/modules/forum/disable" in forum_card and "/modules/forum/uninstall" in forum_card
    redirects = text.split('id="m-redirects"')[1].split("</tr>")[0]
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


def test_the_registry_tab_searches_and_offers_what_is_not_installed(site, tmp_path, monkeypatch):
    import nest.packages  # noqa: PLC0415
    from nest.packages import Offer  # noqa: PLC0415

    def offer(name, title, kind="module", deps=()):
        return Offer(
            name=name, dist=f"acme-{name}", version="1.0.0", type=kind, title=title,
            description="Small things.", source="remote", index="https://r.example/simple/",
            nest=">=0.2,<1", deps=list(deps),
        )  # fmt: skip

    found = {
        "widgets": offer("widgets", "Widgets", deps=["auth"]),
        "forum": offer("forum", "Forum"),
    }
    found["sharp"] = offer("sharp", "Sharp", kind="theme")
    monkeypatch.setattr(nest.packages, "remote_offers", lambda environ=None: found)
    c = admin_client(site, tmp_path)
    page = c.get("/admin/modules?tab=registry&q=widg").text
    row = page.split("<code>widgets</code>")[1].split("</tr>")[0]
    assert "Widgets" in page and "Needs" in row and 'action="/admin/modules/add"' in row
    assert "<code>forum</code>" not in page  # the search
    everything = c.get("/admin/modules?tab=registry").text
    forum = everything.split("<code>forum</code>")[1].split("</tr>")[0]
    assert "installed" in forum and "/admin/modules/add" not in forum  # it has it already
    assert "Install" in everything.split("<code>sharp</code>")[1].split("</tr>")[0]  # a theme
    themes = c.get("/admin/modules?tab=registry&kind=theme").text
    assert "<code>sharp</code>" in themes and "<code>widgets</code>" not in themes
    assert c.get("/admin/modules/registry?q=widg").status_code == 200  # the old address


def test_the_tabs_say_what_has_updates_and_offer_update_all(site, tmp_path, monkeypatch):
    import nest.packages  # noqa: PLC0415
    from nest.packages import Offer  # noqa: PLC0415

    def newer(name):
        return Offer(
            name=name, dist=f"nest-{name}", version="9.0.0", type="module", title=name.title(),
            description="", source="remote", index="https://r.example/simple/", nest=">=0.2,<1",
        )  # fmt: skip

    monkeypatch.setattr(
        nest.packages,
        "remote_offers",
        lambda environ=None: {n: newer(n) for n in ("forum", "auth")},
    )
    c = admin_client(site, tmp_path)
    page = c.get("/admin/modules").text
    assert "Newer versions in the registry: 2." in page and "Update to 9.0.0" in page
    updates = c.get("/admin/modules?tab=updates").text
    assert "Update all (2)" in updates and 'action="/admin/modules/update-all"' in updates
    forum = c.get("/admin/modules/forum").text
    assert "Versions" in forum and "Migrations" in forum
    history = c.get("/admin/modules?tab=history").text
    assert "No change yet." in history or "<table" in history


def test_a_version_change_runs_in_the_background_and_says_when_done(site, tmp_path, monkeypatch):
    """The page answers at once (a proxy would time out on download, backup, migrations);
    it polls the change, and reloads saying what was done, or why not."""
    from nest_admin import changes, modules

    import threading

    monkeypatch.setattr(changes, "SETTLE", 0.0)
    done, go = [], threading.Event()

    def run_nest(request, args, who):
        go.wait(10)  # under way until the test lets it finish
        done.append(args)
        return True, ["forum 0.1.0 → 9.9.9", "backup: x.tar.gz", "something else"]

    monkeypatch.setattr(modules, "_run_nest", run_nest)
    c = admin_client(site, tmp_path)
    r = post(c, "/admin/modules/forum/version", version="9.9.9")
    assert r.status_code == 200 and "Applying forum → 9.9.9" in r.text
    assert 'hx-get="/admin/modules/_change"' in r.text
    again = post(c, "/admin/modules/forum/version", version="9.9.9")
    assert "Another change is under way" in again.text
    go.set()
    for _ in range(50):
        r = c.get("/admin/modules/_change", headers={"HX-Request": "true"})
        if r.headers.get("HX-Refresh") == "true":
            break
        time.sleep(0.1)
    assert r.headers.get("HX-Refresh") == "true"
    assert done == [["version", "forum=9.9.9"]]
    page = c.get("/admin/modules/forum").text
    assert "Applied: forum → 9.9.9." in page and "backup: x.tar.gz" in page
    assert "something else" not in page

    def refused(request, args, who):
        return False, ["forum 9.9.9 needs nest >=9"]

    monkeypatch.setattr(modules, "_run_nest", refused)
    post(c, "/admin/modules/forum/version", version="9.9.9")
    for _ in range(50):
        if c.get("/admin/modules/_change", headers={"HX-Request": "true"}).headers.get(
            "HX-Refresh"
        ):
            break
        time.sleep(0.1)
    page = c.get("/admin/modules/forum").text
    assert "could not be applied" in page and "needs nest &gt;=9" in page
