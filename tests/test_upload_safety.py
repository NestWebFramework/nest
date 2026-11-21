"""What keeps uploads safe: a request's body is limited before anything reads it, an
uploaded picture is read whole and written again without its metadata (a photo's GPS
position, its camera), turned upright, refused when it is not what it claims or would
decode to an enormous image; who uploaded it is kept."""

import io
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_gallery import service
from nest_media import ImageError, clean_image
from PIL import Image

from nest import create_app

PASSWORD = "correct horse battery"
APP = """
module: {name: photos, id: test.app.photos, type: application, version: 0.1.0}
application: {title: Foto, port: 8000, theme: base, languages: [en], max_body_mb: 1}
modules:
  - {name: auth, route: /cont}
  - {name: admin, route: /admin}
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


def photo_with_gps(orientation: int = 1, size=(60, 40)) -> bytes:
    """A JPEG as a phone writes it: the place it was taken, the camera, an orientation."""
    img = Image.new("RGB", size, "blue")
    exif = Image.Exif()
    exif[0x0110] = "PhoneCam 12"  # Model
    exif[0x0112] = orientation  # Orientation
    gps = {1: "N", 2: (46.0, 51.0, 27.0), 3: "E", 4: (22.0, 55.0, 4.5)}  # Morlaca, to the metre
    exif[0x8825] = gps
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def metadata(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as img:
        return dict(img.getexif()), img.size, img.info


# --- the picture, written again -----------------------------------------------------------


def test_a_photo_loses_its_place_and_camera_and_stands_upright():
    original = photo_with_gps(orientation=6)  # taken turned: 60×40 stored, 40×60 seen
    exif, size, _info = metadata(original)
    assert 0x8825 in exif and exif[0x0110] == "PhoneCam 12"
    cleaned, kind = clean_image(original)
    exif, size, info = metadata(cleaned)
    assert kind == "image/jpeg" and exif == {} and "exif" not in info  # no GPS, no camera
    assert size == (40, 60)  # turned as its camera said, the tag gone with the rest


def test_a_png_loses_its_text_and_keeps_its_transparency():
    img = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
    from PIL import PngImagePlugin

    meta = PngImagePlugin.PngInfo()
    meta.add_text("Author", "Someone's home address")
    out = io.BytesIO()
    img.save(out, "PNG", pnginfo=meta)
    cleaned, kind = clean_image(out.getvalue())
    with Image.open(io.BytesIO(cleaned)) as back:
        assert kind == "image/png" and "Author" not in back.info and back.mode == "RGBA"


def test_an_animated_gif_keeps_its_frames():
    frames = [Image.new("RGB", (10, 10), c) for c in ("red", "green", "blue")]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    cleaned, kind = clean_image(out.getvalue())
    with Image.open(io.BytesIO(cleaned)) as back:
        assert kind == "image/gif" and back.n_frames == 3


@pytest.mark.parametrize(
    "data",
    [
        b"\xff\xd8\xff\xe0" + b"<script>alert(1)</script>" * 20,  # starts like a JPEG, is not one
        b"<svg onload=alert(1)>",  # not a picture it takes at all
        photo_with_gps()[:300],  # cut short
    ],
)
def test_what_is_not_a_whole_picture_is_refused(data):
    with pytest.raises(ImageError):
        clean_image(data)


def test_a_decompression_bomb_is_refused_before_it_is_decoded():
    out = io.BytesIO()
    Image.new("L", (4000, 4000), 0).save(out, "PNG")  # small on disk, 16 million pixels
    assert len(out.getvalue()) < 100_000
    with pytest.raises(ImageError, match="too large"):
        clean_image(out.getvalue(), max_pixels=1_000_000)


# --- in the application ---------------------------------------------------------------------


@pytest.fixture
def c(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app, follow_redirects=False) as client:
        client.db = app.state.nest.bindings.get("nest.db")
        client.storage = app.state.nest.bindings.get("nest.storage")
        client.user = create_user(client.db, "ed@example.ro", PASSWORD, roles=("editor",))
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


def test_a_body_over_the_limit_is_refused_before_it_is_read(c):
    anonymous = TestClient(c.app, follow_redirects=False)
    big = b"x" * (2**20 + 1)
    r = anonymous.post(
        "/cont/login", content=big, headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert r.status_code == 413 and "1 MB" in r.text  # said by its length: not read at all

    def chunks():  # a body that does not say its length, counted as it comes
        for _ in range(3):
            yield b"y" * (2**19 + 10)

    r = anonymous.post(
        "/cont/login",
        content=chunks(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413
    assert c.get("/healthz").status_code == 200  # the site goes on


def test_an_upload_is_cleaned_and_its_uploader_kept(c):
    cid = service.create(c.db, "Hramul").id
    r = c.post(
        f"/admin/gallery/{cid}/photos",
        files=[("files", ("telefon.jpg", photo_with_gps(), "image/jpeg"))],
        headers={
            "accept": "application/json",
            "x-csrf-token": c.csrf,
        },  # as the page's script sends it
    )
    assert r.status_code == 200, r.text
    p = service.photos(c.db, cid)[0]
    with c.storage.open(p.key) as f:
        exif, _size, _info = metadata(f.read())
    assert exif == {}  # stored without where it was taken
    assert p.uploaded_by == c.user.id and p.uploaded_at is not None
    polyglot = c.post(
        f"/admin/gallery/{cid}/photos",
        files=[("files", ("x.jpg", b"\xff\xd8\xff\xe0" + b"<html>" * 50, "image/jpeg"))],
        headers={"accept": "application/json", "x-csrf-token": c.csrf},
    )
    assert polyglot.status_code == 400 and "cannot be read" in polyglot.json()["problems"][0]


def test_an_upload_without_a_token_or_a_session_is_refused(c):
    cid = service.create(c.db, "Hramul").id
    files = [("files", ("a.jpg", photo_with_gps(), "image/jpeg"))]
    assert c.post(f"/admin/gallery/{cid}/photos", files=files).status_code == 403  # no token
    stranger = TestClient(c.app, follow_redirects=False)
    stranger.get("/healthz")
    r = stranger.post(
        f"/admin/gallery/{cid}/photos",
        files=files,
        headers={"x-csrf-token": stranger.cookies["nest_csrf"]},
    )
    assert r.status_code in (303, 401, 403) and service.photos(c.db, cid) == []
