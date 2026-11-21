"""Galleries made and arranged in the admin panel: new galleries and albums (an album is a
gallery of galleries), photos uploaded (checked by their bytes and their size), put in
order, removed, a cover chosen; a gallery moved into another album, renamed, deleted."""

import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_gallery import service

from nest import create_app

PASSWORD = "correct horse battery"
APP = """
module: {name: photos, id: test.app.photos, type: application, version: 0.1.0}
application: {title: Foto, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: auth, route: /cont}
  - {name: admin, route: /admin}
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


def _picture(fmt: str, size=(40, 30)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, "green").save(out, fmt)
    return out.getvalue()


JPEG, PNG = _picture("JPEG"), _picture("PNG")  # real pictures: an upload is read whole


@pytest.fixture
def c(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app, follow_redirects=False) as client:
        client.db = app.state.nest.bindings.get("nest.db")
        client.storage = app.state.nest.bindings.get("nest.storage")
        create_user(client.db, "ed@example.ro", PASSWORD, roles=("editor",))
        client.get("/healthz")
        client.post(
            "/cont/login",
            data={
                "csrf_token": client.cookies["nest_csrf"],
                "email": "ed@example.ro",
                "password": PASSWORD,
            },
        )
        client.csrf = client.cookies["nest_csrf"]
        yield client


def make(c, title, parent=""):
    r = c.post(
        "/admin/gallery/new", data={"csrf_token": c.csrf, "title": title, "parent_id": parent}
    )
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def upload(c, cid, *files, json=False):
    headers = {"accept": "application/json"} if json else {}
    return c.post(
        f"/admin/gallery/{cid}/photos",
        data={"csrf_token": c.csrf},
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
        headers=headers,
    )


def save(c, cid, **extra):
    g = service.by_id(c.db, cid)
    photos = service.photos(c.db, cid)
    data = {
        "csrf_token": c.csrf,
        "title": g.title,
        "slug": g.slug,
        "parent_id": str(g.parent_id or ""),
        "description": g.description,
        "published": "1",
        "cover": g.cover,
    }
    data["order"] = [str(p.id) for p in photos]
    for p in photos:
        data[f"alt_{p.id}"], data[f"caption_{p.id}"] = p.alt, p.caption
    data.update(extra)
    return c.post(f"/admin/gallery/{cid}", data=data)


def test_galleries_and_albums_are_made_and_shown_as_a_tree(c):
    album = make(c, "Fotografii vechi și noi")
    winter = make(c, "Iarna în sat", str(album))
    page = c.get("/admin/gallery/").text
    assert "Iarna în sat" in page and 'class="depth-1"' in page and ">album<" in page
    assert (
        service.by_id(c.db, winter).parent_id == album
        and service.by_id(c.db, winter).slug == "iarna-in-sat"
    )
    make(c, "Iarna în sat")  # the same title elsewhere: another address
    assert {g.slug for g, *_ in service.tree(c.db)} >= {"iarna-in-sat", "iarna-in-sat-2"}
    assert (
        c.post("/admin/gallery/new", data={"csrf_token": c.csrf, "title": "  "}).status_code == 303
    )
    assert len(service.tree(c.db)) == 3  # a gallery needs a title


def test_photos_are_uploaded_checked_and_shown(c):
    cid = make(c, "Hramul")
    r = upload(
        c, cid, ("Biserica la hram.JPG", JPEG), ("plan.png", PNG), ("notes.txt", b"just text")
    )
    assert r.status_code == 303
    photos = service.photos(c.db, cid)
    assert [p.key.rsplit("/", 1)[1] for p in photos] == ["biserica-la-hram.jpg", "plan.png"]
    assert (
        all(re.match(r"uploads/\d{4}/\d{2}/", p.key) for p in photos)
        and c.storage.stat(photos[0].key) is not None
    )
    again = upload(c, cid, ("Biserica la hram.jpg", JPEG), json=True).json()
    assert again["added"][0]["key"].endswith("biserica-la-hram-2.jpg") and again["problems"] == []
    refused = upload(c, cid, ("x.jpg", b"GIF? no"), json=True)  # neither by its name
    assert refused.status_code == 400 and "JPEG, PNG" in refused.json()["problems"][0]
    c.app.state.nest.settings.set("gallery.upload_max_mb", 1)
    big = upload(c, cid, ("big.jpg", JPEG + b"\x00" * 2**20), json=True)
    assert big.status_code == 400 and "1 MB" in big.json()["problems"][0]
    page = c.get("/galerii/hramul/").text
    assert page.count("data-lightbox") == 3


def test_photos_are_put_in_order_removed_and_one_made_the_cover(c):
    cid = make(c, "De prin sat")
    upload(c, cid, ("a.jpg", JPEG), ("b.jpg", JPEG), ("c.jpg", JPEG))
    a, b, third = service.photos(c.db, cid)
    assert save(c, cid, order=[str(third.id), str(a.id), str(b.id)]).status_code == 303  # dragged
    assert [p.id for p in service.photos(c.db, cid)] == [third.id, a.id, b.id]
    save(c, cid, move=f"{b.id}:up")  # an arrow, without the script
    assert [p.id for p in service.photos(c.db, cid)] == [third.id, b.id, a.id]
    save(c, cid, remove=str(third.id), cover=a.key)
    assert [p.id for p in service.photos(c.db, cid)] == [b.id, a.id]
    assert service.by_id(c.db, cid).cover == a.key
    assert c.storage.stat(third.key) is not None  # its file stays: an article may show it
    editor = c.get(f"/admin/gallery/{cid}").text
    assert f'value="{a.key}" checked' in editor and "gallery-admin.js" in editor


def test_a_gallery_moves_into_an_album_never_into_its_own(c):
    album, gallery, inner = make(c, "Album"), make(c, "Galerie"), None
    inner = make(c, "Înăuntru", str(gallery))
    assert save(c, gallery, parent_id=str(album)).status_code == 303
    assert service.by_id(c.db, gallery).parent_id == album
    r = save(c, gallery, parent_id=str(inner))
    assert (
        r.status_code == 400 and "nu poate intra în ea însăși" in r.text
    )  # said in the site's language
    assert service.by_id(c.db, gallery).parent_id == album
    editor = c.get(f"/admin/gallery/{gallery}").text  # its own are not offered as its album
    options = re.findall(
        r'<option value="(\d+)"', editor.split('id="parent_id"')[1].split("</select>")[0]
    )
    assert str(inner) not in options and str(gallery) not in options and str(album) in options
    save(c, gallery, slug="Galeria mea")
    assert service.by_id(c.db, gallery).slug == "galeria-mea"
    album_page = c.get("/galerii/album/").text
    assert "Galerie" in album_page  # its tile in the album


def test_a_gallery_is_deleted_only_when_its_title_is_typed(c):
    album = make(c, "Album")
    gallery = make(c, "Galerie", str(album))
    child = make(c, "Copil", str(gallery))
    upload(c, gallery, ("a.jpg", JPEG))
    c.post(f"/admin/gallery/{gallery}/delete", data={"csrf_token": c.csrf, "confirm": "galerie"})
    assert service.by_id(c.db, gallery) is not None
    r = c.post(
        f"/admin/gallery/{gallery}/delete", data={"csrf_token": c.csrf, "confirm": "Galerie"}
    )
    assert r.status_code == 303 and service.by_id(c.db, gallery) is None
    assert service.by_id(c.db, child).parent_id == album  # moved up to its album
    assert service.photos(c.db, gallery) == []
