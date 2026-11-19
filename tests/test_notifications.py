"""Toasts: said by a module, carried by the notifications module to the page seen next."""

import json
import textwrap

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user

from nest import create_app, toast

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: notifications}
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
        c.db = app.state.nest.bindings.get("nest.db")
        create_user(c.db, "ed@example.ro", PASSWORD, roles=("editor",))
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


def save(c, title, **headers):
    return c.post(
        "/admin/content/page/new",
        data={"csrf_token": c.cookies["nest_csrf"], "title": title, "status": "draft"},
        headers=headers,
        follow_redirects=False,
    )


def region(html):
    return html.split('id="toasts"', 1)[1].split("</div>\n<script", 1)[0]


def test_a_save_is_told_on_the_page_after_the_redirect_and_only_there(site):
    r = save(site, "Istoria")
    assert r.status_code == 303 and "nest_toast" in r.headers["set-cookie"]
    page = site.get(r.headers["location"])
    assert 'class="toast toast-success"' in page.text and "Salvat." in region(page.text)
    assert "notifications/toasts.js" in page.text
    assert 'class="notice ok"' not in page.text  # the toast says it; the page does not repeat it
    assert "nest_toast=;" in page.headers["set-cookie"]  # read once: gone
    assert "toast-success" not in region(site.get(r.headers["location"]).text)


def test_htmx_shows_a_failure_at_once_and_a_save_after_its_redirect(site):
    bad = save(site, "", **{"HX-Request": "true"})
    trigger = json.loads(bad.headers["hx-trigger"])["nest:toast"]["items"]
    assert trigger[0]["level"] == "error" and trigger[0]["text"].startswith("Nu s-a salvat")
    assert "nest_toast" not in bad.headers.get("set-cookie", "")
    ok = save(site, "Portul", **{"HX-Request": "true"})
    assert "hx-redirect" in ok.headers and "hx-trigger" not in ok.headers
    assert "nest_toast" in ok.headers["set-cookie"]  # for the page HX-Redirect opens
    assert "Salvat." in region(site.get(ok.headers["hx-redirect"]).text)


def test_what_loads_with_a_page_leaves_its_toast_alone(site):
    r = save(site, "Tradiții")
    css = site.get("/assets/notifications/toasts.css")
    assert "nest_toast" not in css.headers.get("set-cookie", "")
    assert "Salvat." in region(site.get(r.headers["location"]).text)


def test_a_forged_toast_is_not_shown(site):
    import base64

    fake = base64.urlsafe_b64encode(
        json.dumps([{"text": "Ai câștigat!", "level": "success"}]).encode()
    )
    site.cookies.set("nest_toast", fake.decode() + ".0123456789abcdef0123456789abcdef")
    assert "câștigat" not in site.get("/admin/content/").text


def test_a_toast_is_text_never_markup(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    probe = APIRouter()

    @probe.get("/_probe")
    def _probe(request: Request):
        from fastapi.responses import RedirectResponse

        toast(request, "<script>alert(1)</script> gata", "warning")
        toast(request, "x", "nonsense")
        return RedirectResponse("/cont/login", status_code=303)

    app.include_router(probe)
    with TestClient(app) as c:
        page = c.get("/_probe").text
    shown = region(page)
    assert "&lt;script&gt;" in shown and "<script>alert" not in shown
    assert "toast-warning" in shown and "toast-info" in shown  # an unknown level is info


def test_without_the_module_a_toast_is_dropped_and_the_page_says_it(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP).replace("  - {name: notifications}\n", ""), encoding="utf-8"
    )
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        create_user(
            c.app.state.nest.bindings.get("nest.db"), "ed@example.ro", PASSWORD, roles=("editor",)
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ed@example.ro",
                "password": PASSWORD,
            },
        )
        r = save(c, "Istoria")
        assert "nest_toast" not in r.headers.get("set-cookie", "")
        page = c.get(r.headers["location"]).text
        assert 'class="notice ok"' in page and 'id="toasts"' not in page
