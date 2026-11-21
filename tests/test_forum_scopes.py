"""Boards with a scope: not listed, read and written only by those the application lets in
(forum.access), made by another module when first wanted (forum.board); and public boards
that show the accounts' own names (public_names: account), never their emails."""

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_forum import service as forum
from test_forum_messages import HELLO, PASSWORD, csrf

from nest import create_app

SCOPE = "w/settlement:12"


@pytest.fixture
def app(tmp_path):
    app = create_app(HELLO, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    members = {"read": set(), "post": set()}

    def may(key):  # the application's answer: who belongs to the scope
        if key["scope"] != SCOPE:
            return None
        uid = key["user"]
        return {"read": uid in members["read"], "post": uid in members["post"]}

    app.state.nest._lookups.setdefault("forum.access", []).append(("test", may))  # noqa: SLF001
    app.members = members
    return app


def signed_in(app, email, roles=(), name=""):
    c = TestClient(app)
    db = app.state.nest.bindings.get("nest.db")
    user = create_user(db, email, PASSWORD, roles=roles, name=name)
    c.get("/healthz")
    c.post(
        "/auth/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": email, "password": PASSWORD},
    )
    c.uid = user.id
    return c


def test_a_scoped_board_is_made_once_and_kept_from_others(app):
    with TestClient(app) as guest:
        made = app.state.nest.lookup("forum.board", {"scope": SCOPE, "title": "Sfatul obștii"})
        again = app.state.nest.lookup("forum.board", {"scope": SCOPE, "title": "Sfatul obștii"})
        assert made == again and made["url"] == f"/forum/{made['slug']}/"
        assert app.state.nest.lookup("forum.board", {"title": "no scope"}) is None
        public = forum.ensure_board(app.state.nest.bindings.get("nest.db"), "General")

        index = guest.get("/forum/").text
        assert "General" in index and "Sfatul" not in index  # never listed
        assert guest.get(made["url"]).status_code == 404  # a guest: not found

        member = signed_in(app, "ana@example.org", name="Ana")
        stranger = signed_in(app, "ion@example.org", name="Ion")
        app.members["read"] |= {member.uid}
        assert stranger.get(made["url"]).status_code == 404  # not a member: not found either
        page = member.get(made["url"])
        assert page.status_code == 200 and "New topic" not in page.text  # reads, may not post
        assert member.get(f"{made['url']}new").status_code == 404

        app.members["post"] |= {member.uid}
        assert "New topic" in member.get(made["url"]).text
        r = member.post(
            f"{made['url']}new",
            data={"title": "The well", "body": "Who mends the well?"},
            headers=csrf(member),
            follow_redirects=False,
        )
        assert r.status_code == 303
        topic = r.headers["location"]
        assert "Who mends the well?" in member.get(topic).text
        assert stranger.get(topic).status_code == 404  # the topic too
        assert guest.get(topic).status_code == 404
        topic_id = int(topic.split("/t/")[1].split("/")[0])
        refused = stranger.post(
            f"/forum/t/{topic_id}/reply", data={"body": "me too"}, headers=csrf(stranger)
        )
        assert refused.status_code == 404

        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        assert moderator.get(topic).status_code == 200  # moderators everywhere
        assert public.scope is None


def test_live_replies_reach_only_those_who_may_read(app):
    from nest_forum.web import access

    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app):
        b = forum.ensure_board(db, "Sfatul", scope=SCOPE)
        ask = lambda key: app.state.nest.lookup("forum.access", key)  # noqa: E731
        from nest_auth import CurrentUser

        ana = CurrentUser(id=1, email="", name="Ana", roles=frozenset())
        assert access(ask, None, b, True) == (False, False)
        assert access(ask, ana, b, True) == (False, False)
        app.members["read"] |= {1}
        assert access(ask, ana, b, True) == (True, False)
        app.members["post"] |= {1}
        assert access(ask, ana, b, True) == (True, True)
        public = forum.ensure_board(db, "General")
        assert access(ask, None, public, True) == (True, False)


def test_public_boards_may_show_the_accounts_own_names(app, tmp_path):
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app):
        app.state.nest.settings.set("forum.public_names", "account")
        b = forum.ensure_board(db, "General")
        named = signed_in(app, "ana@example.org", name="Ana Pop")
        nameless = signed_in(app, "ion@example.org")
        for c, title in ((named, "Hello"), (nameless, "Hi")):
            c.post(f"/forum/{b.slug}/new", data={"title": title, "body": "first"}, headers=csrf(c))
        page = TestClient(app).get(f"/forum/{b.slug}/").text
        assert "Ana Pop" in page and f"#{nameless.uid}" in page
        assert "@example.org" not in page  # an email never shows


def test_boards_nest_to_any_depth(app):
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        top = forum.ensure_board(db, "Joc")
        mid = forum.ensure_board(db, "Meserii", slug="meserii", parent=top)
        deep = forum.ensure_board(db, "Fierarii", slug="fierarii", parent=mid)
        assert (mid.parent_id, deep.parent_id) == (top.id, mid.id)

        index = guest.get("/forum/").text
        assert "Joc" in index and "Meserii" not in index  # only the forum's own boards
        page = guest.get(f"/forum/{top.slug}/").text
        assert "Meserii" in page and "Fierarii" not in page  # a board shows the ones in it
        down = guest.get(f"/forum/{deep.slug}/").text
        trail = down.split('class="muted forum-trail"')[1].split("</p>")[0]
        assert "Joc" in trail and "Meserii" in trail  # the way back up

        member = signed_in(app, "ana@example.org", name="Ana")
        topic = member.post(
            f"/forum/{deep.slug}/new",
            data={"title": "Nicovala", "body": "Cine o are?"},
            headers=csrf(member),
            follow_redirects=False,
        ).headers["location"]
        assert (
            "Meserii"
            in guest.get(topic).text.split('class="muted forum-trail"')[1].split("</p>")[0]
        )

        assert (
            member.post(
                f"/forum/{top.slug}/boards", data={"title": "X"}, headers=csrf(member)
            ).status_code
            == 403
        )
        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        assert "Add a board here" in moderator.get(f"/forum/{top.slug}/").text
        r = moderator.post(
            f"/forum/{top.slug}/boards",
            data={"title": "Ajutor", "description": "Întrebări"},
            headers=csrf(moderator),
            follow_redirects=False,
        )
        assert r.status_code == 303 and "Ajutor" in guest.get(f"/forum/{top.slug}/").text


def test_a_private_boards_boards_are_as_private(app):
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        made = app.state.nest.lookup("forum.board", {"scope": SCOPE, "title": "Sfatul obștii"})
        root = forum.board(db, made["slug"])
        inner = forum.ensure_board(db, "Hotarul", slug="hotarul", parent=root)
        deeper = forum.ensure_board(db, "Pădurea", slug="padurea", parent=inner)
        assert inner.scope == deeper.scope == SCOPE  # the same members, all the way down
        again = app.state.nest.lookup("forum.board", {"scope": SCOPE, "title": "Sfatul obștii"})
        assert again == made  # the scope's own board is still the outer one

        member = signed_in(app, "ana@example.org", name="Ana")
        stranger = signed_in(app, "ion@example.org", name="Ion")
        app.members["read"] |= {member.uid}
        for b in (inner, deeper):
            assert member.get(f"/forum/{b.slug}/").status_code == 200
            assert stranger.get(f"/forum/{b.slug}/").status_code == 404
            assert guest.get(f"/forum/{b.slug}/").status_code == 404
        assert "Hotarul" not in guest.get("/forum/").text


PANEL = """
module: {name: panel, id: test.app.panel, type: application, version: 0.1.0}
application: {title: Panel, port: 8000, theme: base}
modules:
  - {name: forum, route: /forum}
  - {name: auth, route: /auth}
  - {name: admin, route: /admin}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def test_the_admin_panel_adds_boards_at_any_level(tmp_path):
    root = tmp_path / "panel"
    root.mkdir()
    (root / "module.yml").write_text(PANEL, encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        member = signed_in(app, "ana@example.org", name="Ana")
        assert member.get("/admin/forum/").status_code == 403
        assert (
            member.post(
                "/admin/forum/boards", data={"title": "X"}, headers=csrf(member)
            ).status_code
            == 403
        )

        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        page = moderator.get("/admin/forum/").text
        assert "the forum itself (a first-level board)" in page
        r = moderator.post(
            "/admin/forum/boards",
            data={"title": "Anunțuri"},
            headers=csrf(moderator),
            follow_redirects=False,
        )
        assert r.status_code == 303
        top = forum.board(db, "anunturi")
        assert top is not None and top.parent_id is None and "Anunțuri" in guest.get("/forum/").text
        moderator.post(
            "/admin/forum/boards",
            data={"title": "Lumi noi", "parent": top.slug},
            headers=csrf(moderator),
        )
        inner = next(r.board for r in forum.boards(db, parent_id=top.id))
        assert inner.title == "Lumi noi" and "Lumi noi" in guest.get(f"/forum/{top.slug}/").text
        tree = moderator.get("/admin/forum/").text
        assert tree.index("Anunțuri") < tree.index("— Lumi noi")  # under the one it is in
        assert (
            moderator.post(
                "/admin/forum/boards", data={"title": " "}, headers=csrf(moderator)
            ).status_code
            == 400
        )


def panel_app(tmp_path):
    root = tmp_path / "panel"
    root.mkdir(exist_ok=True)
    (root / "module.yml").write_text(PANEL, encoding="utf-8")
    return create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def test_an_archived_board_is_read_with_all_in_it_and_written_by_no_one(tmp_path):
    app = panel_app(tmp_path)
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        top = forum.ensure_board(db, "Vechi")
        inner = forum.ensure_board(db, "Mai vechi", slug="mai-vechi", parent=top)
        member = signed_in(app, "ana@example.org", name="Ana")
        topic = member.post(
            f"/forum/{inner.slug}/new",
            data={"title": "Moara", "body": "Merge?"},
            headers=csrf(member),
            follow_redirects=False,
        ).headers["location"]
        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        assert (
            member.post("/admin/forum/boards/vechi/archive", headers=csrf(member)).status_code
            == 403
        )
        moderator.post(
            "/admin/forum/boards/vechi/archive", data={"archived": "1"}, headers=csrf(moderator)
        )

        index = guest.get("/forum/").text
        assert "Vechi" in index.split("forum-archive")[1]  # listed apart, under the archive
        page = member.get(f"/forum/{inner.slug}/")  # in an archived board: archived too
        assert page.status_code == 200 and "New topic" not in page.text and "Archived" in page.text
        assert member.get(f"/forum/{inner.slug}/new").status_code == 404
        assert "Merge?" in guest.get(topic).text
        topic_id = int(topic.split("/t/")[1].split("/")[0])
        assert (
            member.post(
                f"/forum/t/{topic_id}/reply", data={"body": "da"}, headers=csrf(member)
            ).status_code
            == 404
        )
        assert (
            moderator.post(
                f"/forum/t/{topic_id}/reply", data={"body": "da"}, headers=csrf(moderator)
            ).status_code
            == 404
        )
        assert (
            moderator.post(
                "/admin/forum/boards",
                data={"title": "Nou", "parent": inner.slug},
                headers=csrf(moderator),
            ).status_code
            == 400
        )

        moderator.post(
            "/admin/forum/boards/vechi/archive", data={"archived": "0"}, headers=csrf(moderator)
        )
        assert "New topic" in member.get(f"/forum/{inner.slug}/").text


def test_an_archived_topic_is_listed_apart_and_closed(tmp_path):
    app = panel_app(tmp_path)
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        b = forum.ensure_board(db, "General")
        member = signed_in(app, "ana@example.org", name="Ana")
        topic = member.post(
            f"/forum/{b.slug}/new",
            data={"title": "Vechituri", "body": "x"},
            headers=csrf(member),
            follow_redirects=False,
        ).headers["location"]
        topic_id = int(topic.split("/t/")[1].split("/")[0])
        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        assert "Delete…" in moderator.get(topic).text
        moderator.post(
            f"/forum/t/{topic_id}/moderate", data={"action": "archive"}, headers=csrf(moderator)
        )

        board = guest.get(f"/forum/{b.slug}/").text
        assert "Vechituri" not in board and "Archived topics (1)" in board
        assert "Vechituri" in guest.get(f"/forum/{b.slug}/?archived=1").text
        assert "Reply" not in member.get(topic).text
        assert (
            member.post(
                f"/forum/t/{topic_id}/reply", data={"body": "y"}, headers=csrf(member)
            ).status_code
            == 400
        )
        post_id = forum.posts(db, topic_id, page=1, per_page=5)[0][0].id
        assert member.get(f"/forum/p/{post_id}/edit").status_code == 404

        moderator.post(
            f"/admin/forum/topics/{topic_id}/archive",
            data={"archived": "0"},
            headers=csrf(moderator),
        )
        assert "Vechituri" in guest.get(f"/forum/{b.slug}/").text


def test_deleting_a_board_takes_every_board_topic_and_post_in_it(tmp_path):
    app = panel_app(tmp_path)
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as guest:
        top = forum.ensure_board(db, "Sus")
        mid = forum.ensure_board(db, "Mijloc", slug="mijloc", parent=top)
        deep = forum.ensure_board(db, "Jos", slug="jos", parent=mid)
        keep = forum.ensure_board(db, "Rămâne")
        member = signed_in(app, "ana@example.org", name="Ana")
        for b, title in ((top, "Unu"), (deep, "Doi"), (keep, "Trei")):
            member.post(
                f"/forum/{b.slug}/new", data={"title": title, "body": "x"}, headers=csrf(member)
            )

        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        assert member.get("/admin/forum/boards/sus/delete").status_code == 403
        confirm = moderator.get("/admin/forum/boards/sus/delete").text
        assert (
            "2 boards in it" in confirm and "2 topics" in confirm and "Delete for good" in confirm
        )
        assert forum.board(db, "sus") is not None  # asking deletes nothing
        assert (
            member.post("/admin/forum/boards/sus/delete", headers=csrf(member)).status_code == 403
        )

        r = moderator.post(
            "/admin/forum/boards/sus/delete", headers=csrf(moderator), follow_redirects=False
        )
        assert r.status_code == 303
        assert [forum.board(db, s) for s in ("sus", "mijloc", "jos")] == [None, None, None]
        from nest_forum.models import Post, Topic
        from sqlalchemy import func, select

        with db.session() as s:
            assert s.scalar(select(func.count()).select_from(Topic)) == 1
            assert s.scalar(select(func.count()).select_from(Post)) == 1
        assert "Trei" in guest.get(f"/forum/{keep.slug}/").text


def test_the_admin_panel_edits_a_board_and_deletes_a_topic(tmp_path):
    app = panel_app(tmp_path)
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app):
        b = forum.ensure_board(db, "General")
        member = signed_in(app, "ana@example.org", name="Ana")
        topic = member.post(
            f"/forum/{b.slug}/new",
            data={"title": "Pleacă", "body": "x"},
            headers=csrf(member),
            follow_redirects=False,
        ).headers["location"]
        topic_id = int(topic.split("/t/")[1].split("/")[0])
        moderator = signed_in(app, "mod@example.org", roles=("moderator",))
        page = moderator.get(f"/admin/forum/boards/{b.slug}").text
        assert "Pleacă" in page and "Archive, with every board in it" in page
        moderator.post(
            f"/admin/forum/boards/{b.slug}",
            data={"title": "Generale", "description": "De toate", "position": "3"},
            headers=csrf(moderator),
        )
        again = forum.board(db, b.slug)
        assert (again.title, again.description, again.position) == ("Generale", "De toate", 3)

        assert "1 topics" in moderator.get(f"/admin/forum/topics/{topic_id}/delete").text
        moderator.post(f"/admin/forum/topics/{topic_id}/delete", headers=csrf(moderator))
        assert forum.topic(db, topic_id) is None
        assert member.get(topic).status_code == 404
