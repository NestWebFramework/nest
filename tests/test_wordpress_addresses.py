"""The addresses a WordPress site had besides its pages, still answered after the move:
old ids in the query, its search, a category's feed, the comments' feed, and the sign-in
and admin addresses in editors' bookmarks."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_content import service
from nest_content.service import EntryData

from nest import create_app

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro]}
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
    with TestClient(app, follow_redirects=False) as c:
        n = app.state.nest
        db, search, types = (
            n.bindings.get("nest.db"),
            n.bindings.get("nest.search"),
            n.module_state["content"]["types"],
        )
        cat = service.ensure_term(db, types, "category", "Știai că", slug="stiai-ca", legacy_id=5)
        service.save_entry(
            db,
            search,
            types,
            EntryData(
                type="post",
                title="Moara",
                status="published",
                terms={"category": [cat.id]},
                legacy_id=40,
            ),
        )
        service.save_entry(
            db,
            search,
            types,
            EntryData(type="page", title="Contact", status="published", legacy_id=115),
        )
        yield c


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("/?p=40", "/stiai-ca/moara/"),
        ("/?page_id=115", "/contact/"),
        ("/?cat=5", "/category/stiai-ca/"),
        ("/?s=moara", "/search?q=moara"),
        ("/comments/feed/", "/feed/"),
        ("/stiai-ca/moara/feed/", "/stiai-ca/moara/"),
        ("/wp-login.php", "/cont/login"),
        ("/wp-admin/", "/admin"),
    ],
)
def test_an_old_address_sends_on(site, old, new):
    r = site.get(old)
    assert r.status_code == 301 and r.headers["location"] == new


def test_a_category_keeps_its_feed(site):
    r = site.get("/category/stiai-ca/feed/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/rss+xml")
    assert "<title>Satul · Știai că</title>" in r.text and "/stiai-ca/moara/" in r.text


def test_an_unknown_id_is_not_found_anywhere_else(site):
    assert site.get("/?page_id=999").status_code == 200  # the home page, as before
    assert site.get("/nothing/feed/").status_code == 404
