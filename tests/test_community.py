"""Comments and redirects: reusable modules, cooperating with content without importing it."""

import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_comments import service as comments
from nest_comments.wordpress import import_dump as import_comments
from nest_content import service as content
from nest_content.service import EntryData
from nest_redirects import service as redirects

from nest import create_app

PASSWORD = "correct horse battery"
APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - name: comments
    route: /comentarii
    config: {allow_guests: true, min_seconds: 0, per_hour: 3}
  - {name: redirects}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


@pytest.fixture
def site(tmp_path, request):
    root = tmp_path / "site"
    root.mkdir()
    manifest = textwrap.dedent(APP)
    for old, new in getattr(request, "param", {}).items():
        manifest = manifest.replace(old, new)
    (root / "module.yml").write_text(manifest, encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        n = app.state.nest
        c.nest, c.db = n, n.bindings.get("nest.db")
        types, search = n.module_state["content"]["types"], n.bindings.get("nest.search")
        c.entry = content.save_entry(
            c.db,
            search,
            types,
            EntryData(
                type="page", title="Biserica", status="published", body="<p>Text</p>", legacy_id=10
            ),
        )
        yield c


def form_of(page: str) -> dict[str, str]:
    form = page[page.index('class="stack comment-form"') :]
    form = form[: form.index("</form>")]
    return dict(re.findall(r'name="(subject|sig|stamp|csrf_token)" value="([^"]+)"', form))


def sign_in(c, email, roles=()):
    create_user(c.db, email, PASSWORD, roles=roles)
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": email, "password": PASSWORD},
    )


def send(c, data, htmx=True):
    headers = {"X-CSRF-Token": c.cookies["nest_csrf"], **({"HX-Request": "true"} if htmx else {})}
    return c.post("/comentarii/post", data=data, headers=headers, follow_redirects=False)


# --- comments --------------------------------------------------------------------------


def test_a_page_embeds_its_thread_and_a_guest_waits_for_a_moderator(site):
    page = site.get("/biserica/").text
    assert "0 comentarii" in page and 'name="author_name"' in page and 'name="website"' in page
    r = send(
        site,
        {
            **form_of(page),
            "author_name": "Ana",
            "body": "Frumoasă <script>x</script>\n\nhttps://ex.ro",
        },
    )
    assert "așteaptă aprobarea" in r.text
    assert "0 comentarii" in site.get("/biserica/").text  # not shown yet
    (waiting,) = comments.queue(site.db)
    assert (
        waiting.subject == f"content.entry:{site.entry.id}" and waiting.address
    )  # kept only as a hash
    sign_in(site, "mod@example.ro", ("moderator",))
    assert "Ana" in site.get("/admin/comments/").text
    site.post(
        f"/admin/comments/{waiting.id}/status",
        data={"status": "approved"},
        headers={"X-CSRF-Token": site.cookies["nest_csrf"]},
    )
    shown = site.get("/biserica/").text
    assert "1 comentariu" in shown and "&lt;script&gt;" in shown and "<script>x" not in shown
    assert '<a href="https://ex.ro" rel="nofollow ugc noopener">' in shown


def test_a_member_is_published_at_once_and_replies_nest(site):
    sign_in(site, "ion@example.ro")
    page = site.get("/biserica/").text
    assert 'name="author_name"' not in page  # a member is not asked who they are
    r = send(site, {**form_of(page), "body": "Prima"})
    assert "a fost publicat" in r.text and "Prima" in r.text
    first = comments.thread(site.db, f"content.entry:{site.entry.id}")[0][0].comment
    for i in range(4):  # deeper than max_depth 3: the deepest replies sit beside their parent
        parent = max(c.id for c in comments.queue(site.db, "approved"))
        send(
            site,
            {
                **form_of(site.get("/biserica/").text),
                "body": f"Răspuns {i}",
                "parent_id": str(parent),
            },
        )
    roots, total = comments.thread(site.db, f"content.entry:{site.entry.id}")
    assert total == 5 and roots[0].comment.id == first.id
    depth = 0
    node = roots[0]
    while node.replies:
        node, depth = node.replies[0], depth + 1
    assert depth == 2


def test_robots_and_forgers_are_turned_away(site):
    page = site.get("/biserica/").text
    fields = {**form_of(page), "author_name": "Bot", "body": "spam"}
    r = send(site, {**fields, "website": "http://spam"})
    assert (
        "așteaptă aprobarea" in r.text and comments.queue(site.db) == []
    )  # the honeypot: told nothing
    assert send(site, {**fields, "sig": "0" * 32}).status_code == 400
    assert send(site, {**fields, "subject": "content.entry:999"}).status_code == 400
    assert "trimiți din nou" in send(site, {**fields, "stamp": "123.abc"}).text
    for _ in range(3):
        send(site, fields)
    assert "Prea multe comentarii" in send(site, fields).text  # per_hour: 3


@pytest.mark.parametrize("site", [{"allow_guests: true, ": ""}], indirect=True)
def test_guests_cannot_comment_unless_allowed(site):
    page = site.get("/biserica/").text
    assert "Autentifică-te pentru a comenta." in page and "comment-form" not in page


def test_without_javascript_a_post_returns_to_the_page(site):
    page = site.get("/biserica/").text
    r = site.post(
        "/comentarii/post",
        data={**form_of(page), "author_name": "Ana", "body": "Salut"},
        headers={"Referer": "http://testserver/biserica/"},
        follow_redirects=False,
    )
    assert (r.status_code, r.headers["location"]) == (303, "/biserica/")
    r = site.post(
        "/comentarii/post",
        data={**form_of(page), "author_name": "Ana", "body": "Salut"},
        headers={"Referer": "https://evil.example/x"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/"


def test_only_moderators_moderate(site):
    assert site.get("/admin/comments/", follow_redirects=False).status_code == 303
    sign_in(site, "ion@example.ro")
    assert site.get("/admin/comments/").status_code == 403


def test_wordpress_comments_follow_their_posts(site, tmp_path):
    dump = tmp_path / "wp.sql"
    dump.write_text(
        textwrap.dedent(r"""
        CREATE TABLE `wp_comments` (
          `comment_ID` bigint(20),
          `comment_post_ID` bigint(20),
          `comment_author` tinytext,
          `comment_author_email` varchar(100),
          `comment_date` datetime,
          `comment_date_gmt` datetime,
          `comment_content` text,
          `comment_approved` varchar(20),
          `comment_type` varchar(20),
          `comment_parent` bigint(20)
        ) ENGINE=InnoDB;
        INSERT INTO `wp_comments` VALUES (1,10,'Ana &amp; Ion','a@b.ro','2013-01-01 10:00:00','2013-01-01 08:00:00','<p>Foarte <b>frumos</b>!</p>','1','',0),(2,10,'Mihai','','2013-01-02 10:00:00','2013-01-02 08:00:00','Mulțumim','1','',1),(3,10,'x','','2013-01-03 10:00:00','2013-01-03 08:00:00','spam','spam','',0),(4,10,'y','','2013-01-03 10:00:00','2013-01-03 08:00:00','ping','0','pingback',0),(5,99,'z','','2013-01-03 10:00:00','2013-01-03 08:00:00','orphan','1','',0),(6,10,'t','','2013-01-03 10:00:00','2013-01-03 08:00:00','gone','trash','',0);
    """),
        encoding="utf-8",
    )
    report = import_comments(site.db, site.nest.lookup, dump)
    assert (report.comments, report.skipped, report.orphans) == (3, 2, [5])
    roots, total = comments.thread(site.db, f"content.entry:{site.entry.id}")
    assert total == 2 and roots[0].comment.author_name == "Ana & Ion"
    assert (
        roots[0].comment.body == "Foarte frumos!"
        and roots[0].replies[0].comment.author_name == "Mihai"
    )
    assert str(roots[0].comment.created_at) == "2013-01-01 08:00:00"
    assert (
        import_comments(site.db, site.nest.lookup, dump).comments == 3
    )  # again: updated, not doubled
    assert comments.thread(site.db, f"content.entry:{site.entry.id}")[1] == 2


# --- redirects -------------------------------------------------------------------------


def test_redirects_answer_after_pages(site):
    redirects.add(site.db, "/index.php?p=10", "/biserica/")
    redirects.add(site.db, "http://satul.ro/vechi/biserica.html", "/biserica/")
    redirects.add(site.db, "/biserica/", "/altundeva/")  # a page exists there: the page wins
    redirects.add(site.db, "/disparut/", "", 410)
    r = site.get("/index.php?p=10", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (301, "/biserica/")
    assert (
        site.get("/vechi/biserica.html", follow_redirects=False).headers["location"] == "/biserica/"
    )
    assert site.get("/biserica/").status_code == 200
    assert (
        site.get("/disparut", follow_redirects=False).status_code == 410
    )  # the slash does not matter
    assert redirects.find(site.db, "/index.php", "p=10").hits == 1


@pytest.mark.parametrize(
    ("source", "target", "status", "message"),
    [
        ("biserica", "/x/", 301, "starting with '/'"),
        ("/a/", "javascript:alert(1)", 301, "http\\(s\\) address"),
        ("/a/", "//evil.example/", 301, "http\\(s\\) address"),
        ("/a/", "/a/", 301, "cannot send to itself"),
        ("/a/", "/b/", 200, "not a redirect"),
    ],
)
def test_bad_redirects_are_refused(site, source, target, status, message):
    with pytest.raises(redirects.RedirectError, match=message):
        redirects.add(site.db, source, target, status)


def test_a_loop_is_refused(site):
    redirects.add(site.db, "/a/", "/b/")
    redirects.add(site.db, "/b/", "/c/")
    with pytest.raises(redirects.RedirectError, match="in a circle"):
        redirects.add(site.db, "/c/", "/a/")


def test_editors_manage_redirects(site, tmp_path):
    assert site.get("/admin/redirects/", follow_redirects=False).status_code == 303
    sign_in(site, "ed@example.ro", ("editor",))
    headers = {"X-CSRF-Token": site.cookies["nest_csrf"]}
    r = site.post(
        "/admin/redirects/",
        data={"source": "/old/", "target": "/biserica/", "status": "301"},
        headers=headers,
        follow_redirects=False,
    )
    assert r.status_code == 303 and "/old/" in site.get("/admin/redirects/").text
    r = site.post(
        "/admin/redirects/",
        data={"source": "/x/", "target": "ftp://x", "status": "301"},
        headers=headers,
    )
    assert r.status_code == 400 and "adresă http(s)" in r.text
    csv_file = tmp_path / "r.csv"
    csv_file.write_text(
        "source,target,status\n/one/,/biserica/,301\n/two/,,410\n/bad/,javascript:x,301\n"
    )
    import os

    from nest.cli import main

    os.environ["NEST_APP_WORKSPACE"] = str(tmp_path / "ws")
    try:
        assert (
            main(["redirects", "import-csv", str(tmp_path / "site"), str(csv_file)]) == 1
        )  # one refused
    finally:
        del os.environ["NEST_APP_WORKSPACE"]
    assert (
        redirects.find(site.db, "/one/").target == "/biserica/"
        and redirects.find(site.db, "/two/").status == 410
    )
