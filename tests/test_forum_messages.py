"""The forum and private messages, on the hello application."""

import contextlib
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_forum import service as forum
from nest_messages import service as messages

from nest import create_app
from nest.realtime import _Subscriber

HELLO = Path(__file__).resolve().parents[1] / "applications" / "hello"
PASSWORD = "correct horse battery"


@pytest.fixture
def app(tmp_path):
    return create_app(HELLO, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def client(app, email=None, roles=(), name=""):
    c = TestClient(app)
    db = app.state.nest.bindings.get("nest.db")
    if email:
        with contextlib.suppress(Exception):  # already there
            create_user(db, email, PASSWORD, roles=roles, name=name)
        c.get("/healthz")
        c.post(
            "/auth/login",
            data={"csrf_token": c.cookies["nest_csrf"], "email": email, "password": PASSWORD},
        )
    c.db = db
    return c


def csrf(c):
    c.get("/healthz")
    return {"X-CSRF-Token": c.cookies["nest_csrf"]}


def listen(app, channel):
    """Follow a channel the way an open page does, and read what reaches it."""
    sub = _Subscriber()
    app.state.nest.broker._subscribers[channel].add(sub)

    def received():
        out = []
        while not sub.queue.empty():
            out.append(sub.queue.get_nowait())
        return out

    return received


# --- forum -----------------------------------------------------------------------------


def test_members_start_topics_and_replies_arrive_live(app):
    with client(app, "ana@example.ro", name="Ana") as ana, client(app) as guest:
        board = forum.ensure_board(ana.db, "Satul", description="Despre sat")
        assert "Satul" in guest.get("/forum/").text
        assert (
            guest.get("/forum/satul/new", follow_redirects=False).status_code == 303
        )  # sign in first
        r = ana.post(
            "/forum/satul/new",
            data={"title": "Hramul din august", "body": "Cine vine?"},
            headers=csrf(ana),
            follow_redirects=False,
        )
        assert r.status_code == 303
        url = r.headers["location"]
        assert re.fullmatch(r"/forum/t/\d+/hramul-din-august", url)
        topic_id = int(url.split("/")[3])
        page = guest.get(url).text
        assert (
            "Cine vine?" in page
            and f"topic=forum.topic.{topic_id}" in page
            and 'sse-swap="post"' in page
        )
        assert "Autentifică-te pentru a răspunde." in page or "Sign in to reply." in page

        received = listen(app, f"forum.topic.{topic_id}")
        r = ana.post(
            f"/forum/t/{topic_id}/reply",
            data={"body": "Eu, sigur. <b>Da</b>"},
            headers={**csrf(ana), "HX-Request": "true"},
        )
        assert r.text.lstrip().startswith(
            '<form id="reply"'
        )  # a fresh form; the post comes over SSE
        ((event, html),) = received()
        assert event == "post" and "Eu, sigur. &lt;b&gt;Da&lt;/b&gt;" in html and "Ana" in html
        assert "/edit" not in html  # what everyone receives has no one's controls
        t = forum.topic(ana.db, topic_id)
        assert t.posts == 2 and t.last_author_id is not None
        assert (
            guest.get(f"/forum/t/{topic_id}/wrong-slug", follow_redirects=False).headers["location"]
            == url
        )
        assert board.id == t.board_id


def test_authors_edit_for_a_while_and_moderators_always(app):
    with (
        client(app, "ana@example.ro") as ana,
        client(app, "ion@example.ro") as ion,
        client(app, "mod@example.ro", ("moderator",)) as mod,
    ):
        b = forum.ensure_board(ana.db, "Satul")
        t, p = forum.start_topic(
            ana.db, b, ana.get("/healthz") and forum_user(ana), "Titlu", "Text"
        )
        assert ana.get(f"/forum/p/{p.id}/edit").status_code == 200
        assert ion.get(f"/forum/p/{p.id}/edit").status_code == 404
        r = ana.post(
            f"/forum/p/{p.id}/edit",
            data={"body": "Text nou"},
            headers={**csrf(ana), "HX-Request": "true"},
        )
        assert "Text nou" in r.text and forum.post(ana.db, p.id).edited_at is not None
        with ana.db.session() as s, s.begin():  # an hour later
            s.get(type(p), p.id).created_at -= timedelta(hours=1)
        assert ana.get(f"/forum/p/{p.id}/edit").status_code == 404
        assert mod.get(f"/forum/p/{p.id}/edit").status_code == 200
        mod.post(f"/forum/t/{t.id}/moderate", data={"action": "lock"}, headers=csrf(mod))
        r = ana.post(
            f"/forum/t/{t.id}/reply",
            data={"body": "încă unul"},
            headers={**csrf(ana), "HX-Request": "true"},
        )
        assert "închis" in r.text or "closed" in r.text
        mod.post(f"/forum/t/{t.id}/moderate", data={"action": "hide"}, headers=csrf(mod))
        assert ion.get(f"/forum/t/{t.id}/titlu").status_code == 404
        assert mod.get(f"/forum/t/{t.id}/titlu").status_code == 200
        assert (
            ion.post(
                f"/forum/t/{t.id}/moderate", data={"action": "show"}, headers=csrf(ion)
            ).status_code
            == 403
        )


def forum_user(c):
    from nest_auth.sessions import user_for

    return user_for(c.db, c.cookies["nest_session"], days=14).id


def test_posting_is_limited_per_minute(app):
    with client(app, "ana@example.ro") as ana:
        b = forum.ensure_board(ana.db, "Satul")
        t, _ = forum.start_topic(ana.db, b, forum_user(ana), "Titlu", "Text")
        for i in range(4):
            ana.post(
                f"/forum/t/{t.id}/reply",
                data={"body": f"r{i}"},
                headers={**csrf(ana), "HX-Request": "true"},
            )
        r = ana.post(
            f"/forum/t/{t.id}/reply",
            data={"body": "prea mult"},
            headers={**csrf(ana), "HX-Request": "true"},
        )
        assert "un minut" in r.text or "a minute" in r.text


def test_a_private_forum_hides_everything_from_guests(tmp_path):
    root = tmp_path / "hello"
    import shutil

    shutil.copytree(HELLO, root)
    m = (
        (root / "module.yml")
        .read_text()
        .replace(
            "  - name: forum\n    route: /forum\n",
            "  - name: forum\n    route: /forum\n    config: {public_read: false}\n",
        )
    )
    (root / "module.yml").write_text(m)
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with client(app) as guest, client(app, "ana@example.ro") as ana:
        assert guest.get("/forum/").status_code == 404 and ana.get("/forum/").status_code == 200
        assert guest.get("/_nest/events?topic=forum.topic.1").status_code == 403


# --- messages --------------------------------------------------------------------------


def test_members_write_to_each_other_and_messages_arrive_live(app):
    with (
        client(app, "ana@example.ro", name="Ana") as ana,
        client(app, "ion@example.ro", name="Ion") as ion,
    ):
        r = ana.post(
            "/mesaje/new",
            data={"to": "ion@example.ro", "subject": "Hram", "body": "Vii?"},
            headers=csrf(ana),
            follow_redirects=False,
        )
        assert r.status_code == 303
        conv = int(r.headers["location"].rsplit("/", 1)[1])
        ion_id = forum_user(ion)
        assert messages.unread_count(ion.db, ion_id) == 1
        inbox = ion.get("/mesaje/").text
        assert "Ana" in inbox and "Hram" in inbox and 'class="unread"' in inbox
        assert f"topic=messages.user.{ion_id}" in inbox

        page = ion.get(f"/mesaje/{conv}").text
        assert "Vii?" in page and messages.unread_count(ion.db, ion_id) == 0  # read now
        ana_hears = listen(app, f"messages.user.{forum_user(ana)}")
        ion_hears = listen(app, f"messages.user.{ion_id}")
        ion.post(
            f"/mesaje/{conv}/reply",
            data={"body": "Sigur!"},
            headers={**csrf(ion), "HX-Request": "true"},
        )
        to_ana, to_ion = dict(ana_hears()), dict(ion_hears())
        assert (
            "Sigur!" in to_ana[f"conversation-{conv}"]
            and "mine" not in to_ana[f"conversation-{conv}"]
        )
        assert 'class="message mine"' in to_ion[f"conversation-{conv}"]  # rendered for each reader
        assert to_ana["inbox"] == "1" and to_ion["inbox"] == "0"


def test_a_conversation_is_for_its_participants_only(app):
    with (
        client(app, "ana@example.ro") as ana,
        client(app, "ion@example.ro") as ion,
        client(app, "eva@example.ro") as eva,
    ):
        c, _ = messages.start(ana.db, forum_user(ana), [forum_user(ion)], "Secret", "doar noi")
        assert eva.get(f"/mesaje/{c.id}").status_code == 404
        assert (
            eva.post(f"/mesaje/{c.id}/reply", data={"body": "x"}, headers=csrf(eva)).status_code
            == 404
        )
        eva_id = forum_user(eva)
        assert eva.get(f"/_nest/events?topic=messages.user.{forum_user(ana)}").status_code == 403
        assert "Secret" not in eva.get("/mesaje/").text and eva_id


def test_recipients_must_exist_and_writing_to_oneself_is_refused(app):
    with client(app, "ana@example.ro") as ana:
        r = ana.post(
            "/mesaje/new", data={"to": "nimeni@example.ro", "body": "x"}, headers=csrf(ana)
        )
        assert r.status_code == 400 and "nimeni@example.ro" in r.text
        r = ana.post("/mesaje/new", data={"to": "ana@example.ro", "body": "x"}, headers=csrf(ana))
        assert r.status_code == 400
        assert ana.get("/mesaje/").status_code == 200


def test_archiving_hides_until_the_next_message(app):
    with client(app, "ana@example.ro") as ana, client(app, "ion@example.ro") as ion:
        c, _ = messages.start(ana.db, forum_user(ana), [forum_user(ion)], "Arhivă", "x")
        ion.post(f"/mesaje/{c.id}/archive", headers=csrf(ion))
        assert (
            "Arhivă" not in ion.get("/mesaje/").text
            and "Arhivă" in ion.get("/mesaje/?archived=1").text
        )
        messages.reply(ana.db, c.id, forum_user(ana), "din nou")
        assert "Arhivă" in ion.get("/mesaje/").text
