"""Categories and tags in the editor: made, renamed, moved and deleted, the moved
addresses sent on; and the content browsed a category at a time."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_content import service
from nest_content.service import EntryData

from nest import create_app

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: redirects}
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
        n = app.state.nest
        c.db, c.search, c.types = (
            n.bindings.get("nest.db"),
            n.bindings.get("nest.search"),
            n.module_state["content"]["types"],
        )
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
        c.csrf = c.cookies["nest_csrf"]
        yield c


def add(site, name, parent=""):
    r = site.post(
        "/admin/content/taxonomies/category/new",
        data={
            "csrf_token": site.csrf,
            "name": name,
            "slug": "",
            "parent_id": parent,
            "description": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return service.term_by(
        site.db, "category", slug=service.slugify(name) if hasattr(service, "slugify") else name
    )


def term(site, slug):
    return service.term_by(site.db, "category", slug=slug)


def write(site, title, *term_ids):
    return service.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="post",
            title=title,
            status="published",
            body="<p>x</p>",
            terms={"category": list(term_ids)},
        ),
    )


def test_categories_are_made_nested_and_listed(site):
    add(site, "Despre sat")
    add(site, "Biserici", term(site, "despre-sat").id)
    page = site.get("/admin/content/taxonomies/category").text
    assert "Despre sat" in page and "/category/despre-sat/biserici/" in page
    assert 'class="depth-1"' in page  # inside its parent
    refused = site.post(
        "/admin/content/taxonomies/category/new",
        data={"csrf_token": site.csrf, "name": "Biserici", "slug": "", "parent_id": ""},
    )
    assert refused.status_code == 400 and "Alta are deja adresa" in refused.text


def test_renaming_moves_the_addresses_and_the_old_ones_send_on(site):
    add(site, "Istorie")
    t = term(site, "istorie")
    e = write(site, "Biserica veche", t.id)
    assert e.path == "/istorie/biserica-veche/"
    r = site.post(
        f"/admin/content/taxonomies/category/{t.id}",
        data={
            "csrf_token": site.csrf,
            "name": "Istoria satului",
            "slug": "istoria-satului",
            "parent_id": "",
            "description": "Din 1493.",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert service.entry(site.db, e.id).path == "/istoria-satului/biserica-veche/"
    old = site.get("/istorie/biserica-veche/", follow_redirects=False)
    assert old.status_code == 301 and old.headers["location"] == "/istoria-satului/biserica-veche/"
    assert (
        site.get("/category/istorie/", follow_redirects=False).headers["location"]
        == "/category/istoria-satului/"
    )
    # and back: the new address is a page again, the old sends on, no circle
    site.post(
        f"/admin/content/taxonomies/category/{t.id}",
        data={
            "csrf_token": site.csrf,
            "name": "Istorie",
            "slug": "istorie",
            "parent_id": "",
            "description": "",
        },
    )
    assert site.get("/istorie/biserica-veche/").status_code == 200
    assert (
        site.get("/istoria-satului/biserica-veche/", follow_redirects=False).headers["location"]
        == "/istorie/biserica-veche/"
    )


def test_a_category_cannot_go_inside_its_own(site):
    add(site, "Sus")
    add(site, "Jos", term(site, "sus").id)
    r = site.post(
        f"/admin/content/taxonomies/category/{term(site, 'sus').id}",
        data={
            "csrf_token": site.csrf,
            "name": "Sus",
            "slug": "sus",
            "parent_id": str(term(site, "jos").id),
        },
    )
    assert r.status_code == 400 and "în ea însăși" in r.text


def test_deleting_keeps_the_entries_and_moves_the_children_up(site):
    add(site, "Tradiții")
    add(site, "Port", term(site, "traditii").id)
    trad, port = term(site, "traditii"), term(site, "port")
    e = write(site, "Nedeia", trad.id)
    site.post(
        f"/admin/content/taxonomies/category/{trad.id}/delete", data={"csrf_token": site.csrf}
    )
    assert term(site, "traditii") is None
    assert term(site, "port").parent_id is None and term(site, "port").path == "/category/port/"
    moved = service.entry(site.db, e.id)
    assert moved is not None and moved.path == "/uncategorized/nedeia/"  # kept, without it
    assert (
        site.get("/traditii/nedeia/", follow_redirects=False).headers["location"]
        == "/uncategorized/nedeia/"
    )
    assert port.id  # still there


def test_the_content_is_browsed_a_category_at_a_time(site):
    add(site, "Despre sat")
    add(site, "Drumeții")
    sat, drum = term(site, "despre-sat"), term(site, "drumetii")
    write(site, "Istoria", sat.id)
    write(site, "Cu bicicleta", drum.id)
    write(site, "Fără loc")
    home = site.get("/admin/content/").text
    assert f'href="/admin/content/post?category={sat.id}"' in home and "Fără categorie" in home
    assert "Categorii și etichete" in home and 'href="/admin/content/taxonomies/category"' in home
    page = site.get(f"/admin/content/post?category={drum.id}").text
    rows = page.split("<tbody>")[1]
    assert "Cu bicicleta" in rows and "Istoria" not in rows
    assert (
        "Gestionează categoriile" in page and f"/admin/content/post/new?category={drum.id}" in page
    )
    loose = site.get("/admin/content/post?category=none").text.split("<tbody>")[1]
    assert "Fără loc" in loose and "Istoria" not in loose
    new = site.get(f"/admin/content/post/new?category={drum.id}").text
    assert f'name="terms_category" value="{drum.id}" checked' in new  # "New" from a category: in it
