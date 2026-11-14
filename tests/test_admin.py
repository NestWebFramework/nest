"""The admin panel: modules give it their pages; it shows each user the pages its roles open."""

import textwrap

from fastapi.testclient import TestClient
from nest_auth.sessions import create_user

from nest import create_app

APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base}
modules:
  - {name: content, route: /}
  - {name: redirects}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


def make(tmp_path, manifest=APP):
    root = tmp_path / "site"
    root.mkdir(exist_ok=True)
    (root / "module.yml").write_text(textwrap.dedent(manifest), encoding="utf-8")
    return create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def sign_in(c, app, email, roles):
    create_user(app.state.nest.bindings.get("nest.db"), email, "correct horse battery", roles=roles)
    c.get("/healthz")
    c.cookies.clear()
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={
            "csrf_token": c.cookies["nest_csrf"],
            "email": email,
            "password": "correct horse battery",
        },
    )


def test_the_panel_gathers_the_modules_pages(tmp_path):
    app = make(tmp_path)
    nest = app.state.nest
    assert nest.admin_root == "/admin"
    assert [
        (p.module, p.title, p.role, p.base) for p in sorted(nest.admin_pages, key=lambda p: p.order)
    ] == [
        ("content", "Content", "editor", "/admin/content"),
        ("redirects", "Redirects", "editor", "/admin/redirects"),
    ]
    with TestClient(app) as c:
        assert c.get("/admin/", follow_redirects=False).status_code == 303  # sign in first
        sign_in(c, app, "ed@example.ro", ("editor",))
        page = c.get("/admin/").text
        assert 'href="/admin/content/"' in page and 'href="/admin/redirects/"' in page
        editor = c.get("/admin/content/").text
        assert (
            'aria-current="page"' in editor and "/admin/redirects/" in editor
        )  # the panel's own menu
        assert c.get("/admin/redirects/").status_code == 200
        sign_in(c, app, "reader@example.ro", ())
        assert "Nothing here is open to you" in c.get("/admin/").text
        assert c.get("/admin/content/").status_code == 403


def test_without_the_panel_admin_pages_are_not_served(tmp_path, caplog):
    app = make(tmp_path, APP.replace("  - {name: admin, route: /admin}\n", ""))
    assert app.state.nest.admin_root is None
    assert "no module is the admin panel" in caplog.text
    with TestClient(app) as c:
        assert c.get("/admin/content/").status_code == 404
