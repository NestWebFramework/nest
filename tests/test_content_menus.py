"""The menu manager (Admin → Content → Menus): menus made, the theme's locations said,
links to a page, a category, a module's pages and an address, moved and nested, renamed,
removed; the site's menu shows them at once."""

import textwrap

import pytest
from nest_auth.sessions import create_user
from nest_content import service
from nest_content.models import Menu, MenuItem
from sqlalchemy import select
from test_content_languages import PASSWORD, start

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [en]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: forum, route: /forum}
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
    c = start(root, tmp_path / "ws")
    create_user(c.db, "ed@example.org", PASSWORD, roles=("editor",))
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={
            "csrf_token": c.cookies["nest_csrf"],
            "email": "ed@example.org",
            "password": PASSWORD,
        },
    )
    c.csrf = c.cookies["nest_csrf"]
    yield c
    c.__exit__(None, None, None)


def post(c, to, **data):
    return c.post(to, data={"csrf_token": c.csrf, **data})


def items(c, slug="main"):
    with c.db.session() as s:
        m = s.scalar(select(Menu).where(Menu.slug == slug))
        return list(
            s.scalars(select(MenuItem).where(MenuItem.menu_id == m.id).order_by(MenuItem.position))
        )


def test_a_menu_is_made_and_filled_without_code(site):
    page = site.get("/admin/content/menus").text
    assert "The theme has a place for: main" in page
    r = post(site, "/admin/content/menus", title="Main menu", slug="main")
    assert r.status_code == 303
    menu_url = r.headers["location"]
    assert "✓" in site.get("/admin/content/menus").text  # shown by the theme now

    entry = service.save_entry(
        site.db, site.search, site.types,
        service.EntryData(type="page", title="Despre sat", status="published", body="<p>Sat.</p>"),
    )  # fmt: skip
    editor = site.get(menu_url).text
    assert "Forum (/forum/)" in editor  # the forum offers a link to its pages (offers.menu)
    add = menu_url + "/items"
    assert post(site, add, kind="entry", entry_id=str(entry.id)).status_code == 303
    assert (
        post(site, add, kind="module", module_url="/forum/", module_title="Forum").status_code
        == 303
    )
    assert (
        post(
            site, add, kind="custom", url="https://example.org/", title="Elsewhere", new_window="1"
        ).status_code
        == 303
    )
    assert (
        post(site, add, kind="custom", url="javascript:alert(1)", title="X").status_code == 200
    )  # refused
    assert post(site, add, kind="custom", url="/x/").status_code == 200  # an address needs a label
    home = site.get("/despre-sat/").text
    menu_html = home.split('class="menu"')[1].split("</ul>")[0]
    assert "Despre sat" in menu_html and 'href="/forum/"' in menu_html and "Elsewhere" in menu_html
    assert 'target="_blank"' in menu_html and "javascript:" not in home

    first, forum, elsewhere = items(site)
    post(site, f"/admin/content/menus/items/{forum.id}/move", action="up")
    assert [i.id for i in items(site)][:2] == [forum.id, first.id]
    post(
        site, f"/admin/content/menus/items/{elsewhere.id}/move", action="in"
    )  # under the one above
    assert next(i for i in items(site) if i.id == elsewhere.id).parent_id == first.id
    post(site, f"/admin/content/menus/items/{elsewhere.id}/move", action="out")
    assert next(i for i in items(site) if i.id == elsewhere.id).parent_id is None
    post(site, f"/admin/content/menus/items/{forum.id}", title="Discuții")
    assert "Discuții" in site.get("/despre-sat/").text
    post(site, f"/admin/content/menus/items/{forum.id}/delete")
    assert forum.id not in [i.id for i in items(site)]
    assert "Discuții" not in site.get("/despre-sat/").text

    menu_id = int(menu_url.rsplit("/", 1)[1])
    post(site, f"/admin/content/menus/{menu_id}", action="delete")
    with site.db.session() as s:
        assert s.get(Menu, menu_id) is None


def test_only_editors_manage_menus(site):
    site.cookies.clear()
    assert site.get("/admin/content/menus").status_code in (303, 401, 403)
