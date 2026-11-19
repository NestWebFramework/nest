"""The content module: types, entries, paths, HTML, media, editing, and moving WordPress in."""

import re
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_content import service
from nest_content.html import autop, sanitize
from nest_content.service import EntryData
from nest_content.types import Registry, TypesError, build_path
from nest_content.wordpress import import_dump, rewrite
from nest_db.mysqldump import Dump, DumpError
from nest_storage import StorageError, clean_key

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
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
content_types:
  event:
    title: Evenimente
    path: "/evenimente/{year}/{slug}/"
    taxonomies: [category]
    fields:
      starts: {type: datetime, label: Începe, required: true}
      seats: {type: integer, label: Locuri}
      kind: {type: select, choices: [hram, nedeie]}
"""

WP_DUMP = r"""
-- MySQL dump 10.13
CREATE TABLE `wp_options` (
  `option_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `option_name` varchar(191) NOT NULL DEFAULT '',
  `option_value` longtext NOT NULL,
  `autoload` varchar(20) NOT NULL DEFAULT 'yes',
  PRIMARY KEY (`option_id`)
) ENGINE=InnoDB;
INSERT INTO `wp_options` VALUES (1,'siteurl','http://satul.ro','yes'),(2,'home','http://satul.ro','yes'),(3,'permalink_structure','/%category%/%postname%/','yes'),(4,'show_on_front','page','yes'),(5,'page_on_front','20','yes'),(6,'posts_per_page','5','yes');
CREATE TABLE `wp_terms` (
  `term_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL DEFAULT '',
  `slug` varchar(200) NOT NULL DEFAULT '',
  `term_group` bigint(10) NOT NULL DEFAULT '0',
  PRIMARY KEY (`term_id`)
) ENGINE=InnoDB;
INSERT INTO `wp_terms` VALUES (2,'Despre sat','despre-sat',0),(3,'Biserici','biserici',0),(4,'istorie','istorie',0),(5,'Meniu','meniu',0);
CREATE TABLE `wp_term_taxonomy` (
  `term_taxonomy_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `term_id` bigint(20) unsigned NOT NULL DEFAULT '0',
  `taxonomy` varchar(32) NOT NULL DEFAULT '',
  `description` longtext NOT NULL,
  `parent` bigint(20) unsigned NOT NULL DEFAULT '0',
  `count` bigint(20) NOT NULL DEFAULT '0',
  PRIMARY KEY (`term_taxonomy_id`)
) ENGINE=InnoDB;
INSERT INTO `wp_term_taxonomy` VALUES (12,2,'category','',0,1),(13,3,'category','Lăcașuri',2,1),(14,4,'post_tag','',0,1),(15,5,'nav_menu','',0,2);
CREATE TABLE `wp_term_relationships` (
  `object_id` bigint(20) unsigned NOT NULL DEFAULT '0',
  `term_taxonomy_id` bigint(20) unsigned NOT NULL DEFAULT '0',
  `term_order` int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`object_id`,`term_taxonomy_id`)
) ENGINE=InnoDB;
INSERT INTO `wp_term_relationships` VALUES (10,13,0),(10,14,0),(11,12,0),(30,15,0),(31,15,0);
CREATE TABLE `wp_posts` (
  `ID` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `post_author` bigint(20) unsigned NOT NULL DEFAULT '0',
  `post_date` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `post_content` longtext NOT NULL,
  `post_title` text NOT NULL,
  `post_excerpt` text NOT NULL,
  `post_status` varchar(20) NOT NULL DEFAULT 'publish',
  `post_name` varchar(200) NOT NULL DEFAULT '',
  `post_parent` bigint(20) unsigned NOT NULL DEFAULT '0',
  `menu_order` int(11) NOT NULL DEFAULT '0',
  `post_type` varchar(20) NOT NULL DEFAULT 'post',
  `post_mime_type` varchar(100) NOT NULL DEFAULT '',
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB;
INSERT INTO `wp_posts` VALUES (10,1,'2012-12-01 10:00:00','Biserica a fost ridicată în 1791.\n\nAre o <strong>pictură</strong> veche.\n<img src=\"http://79.118.74.35/satul/wp-content/uploads/2012/12/biserica.jpg\" onerror=\"alert(1)\">\n<script>alert(\'x\')</script>\n[catlist categorypage=\"yes\"]','Biserica Ortodoxă din sat','','publish','biserica-din-sat',0,0,'post',''),(11,1,'2012-12-02 10:00:00','Satul e la poalele muntelui. Vezi <a href=\"http://satul.ro/biserici/biserica-din-sat/\">biserica</a>.','Așezarea','','publish','asezarea',0,0,'post',''),(12,1,'2012-12-03 10:00:00','Ciornă','Nepublicat','','draft','nepublicat',0,0,'post',''),(20,1,'2012-12-01 09:00:00','Bine ai venit!','Prima pagină','','publish','prima-pagina',0,0,'page',''),(21,1,'2012-12-01 09:00:00','Istoria pe scurt.','Istoria','','publish','istoria',20,1,'page',''),(25,1,'2012-12-01 09:00:00','','biserica','','inherit','biserica',10,0,'attachment','image/jpeg'),(30,1,'2012-12-01 09:00:00','','','','publish','30',0,1,'nav_menu_item',''),(31,1,'2012-12-01 09:00:00','','Acasă','','publish','31',0,2,'nav_menu_item',''),(40,1,'2012-12-01 09:00:00','x','Galerie','','publish','galerie',0,0,'bwg_gallery','');
CREATE TABLE `wp_postmeta` (
  `meta_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `post_id` bigint(20) unsigned NOT NULL DEFAULT '0',
  `meta_key` varchar(255) DEFAULT NULL,
  `meta_value` longtext,
  PRIMARY KEY (`meta_id`)
) ENGINE=InnoDB;
INSERT INTO `wp_postmeta` VALUES (1,25,'_wp_attached_file','2012/12/biserica.jpg'),(2,25,'_wp_attachment_image_alt','Biserica'),(3,10,'_thumbnail_id','25'),(4,30,'_menu_item_type','taxonomy'),(5,30,'_menu_item_object_id','2'),(6,30,'_menu_item_menu_item_parent','0'),(7,31,'_menu_item_type','custom'),(8,31,'_menu_item_url','http://satul.ro/'),(9,31,'_menu_item_menu_item_parent','0');
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        n = app.state.nest
        c.nest = n
        c.db, c.search, c.storage = (
            n.bindings.get(k) for k in ("nest.db", "nest.search", "nest.storage")
        )
        c.types = n.module_state["content"]["types"]
        yield c


@pytest.fixture
def wordpress(tmp_path, site):
    dump = tmp_path / "wp.sql"
    dump.write_text(WP_DUMP, encoding="utf-8")
    uploads = tmp_path / "uploads" / "2012" / "12"
    uploads.mkdir(parents=True)
    (uploads / "biserica.jpg").write_bytes(b"\xff\xd8 big")
    (uploads / "biserica-300x200.jpg").write_bytes(b"\xff\xd8 small")
    (uploads / "biserica-copy.jpg").write_bytes(b"not a resized copy")
    report = import_dump(
        site.db,
        site.search,
        site.storage,
        site.types,
        dump,
        uploads=tmp_path / "uploads",
        settings=site.nest.settings,
    )
    site.report = report
    return site


def sign_in(c: TestClient, roles=("editor",)) -> None:
    create_user(c.db, "ed@example.ro", PASSWORD, roles=roles)
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": "ed@example.ro", "password": PASSWORD},
    )


# --- mysqldump -------------------------------------------------------------------------


def test_mysqldump_reads_values_and_escapes():
    dump = Dump.parse(
        "CREATE TABLE `t` (\n  `a` int,\n  `b` text,\n  `c` blob\n) ENGINE=InnoDB;\n"
        "INSERT INTO `t` VALUES (1,'it\\'s ''quoted'' \\\\ \\n line',0x6869),(-2,NULL,'a,b)c');\n"
        "INSERT INTO `t` (`b`,`a`) VALUES ('x',3);\n"
    )
    rows = list(dump.rows("t"))
    assert rows[0] == {"a": 1, "b": "it's 'quoted' \\ \n line", "c": b"hi"}
    assert rows[1] == {"a": -2, "b": None, "c": "a,b)c"}
    assert rows[2] == {"b": "x", "a": 3}
    with pytest.raises(DumpError, match="no CREATE TABLE"):
        list(Dump.parse("INSERT INTO `u` VALUES (1);").rows("u"))


# --- HTML ------------------------------------------------------------------------------


def test_sanitize_keeps_content_and_drops_what_runs():
    clean = sanitize(
        '<p class="lead" style="color:red" onclick="x()">Text <a href="javascript:alert(1)">a</a> '
        '<a href="/local">b</a> <img src="/media/x.jpg" onerror="alert(1)"></p><script>x</script>'
        '<iframe src="https://evil"></iframe><p>&nbsp;</p><h2>Titlu</h2>'
    )
    assert '<p class="lead">' in clean and "style" not in clean and "onclick" not in clean
    assert "javascript" not in clean and 'href="/local"' in clean and "onerror" not in clean
    assert "<script>" not in clean and "iframe" not in clean and "<p>&nbsp;</p>" not in clean
    assert "<h2>Titlu</h2>" in clean


def test_autop_is_wordpress_paragraphs():
    assert autop("Unu\n\nDoi\nTrei") == "<p>Unu</p>\n<p>Doi<br>\nTrei</p>"
    assert autop("<h2>T</h2>\nText") == "<h2>T</h2>\n<p>Text</p>"
    assert autop("") == ""


def test_shortcodes_only_in_text_and_unknown_ones_stay():
    from nest.shortcodes import ShortcodeError, Shortcodes

    registry = Shortcodes()
    registry.register("hello", "test", lambda attrs, ctx: f"<b>{attrs.get('name', '?')}</b>")
    out = str(
        registry.expand('<p>[hello name="Ana"] [HELLO] [nope x=1]</p><a title="[hello]">t</a>')
    )
    assert (
        "<b>Ana</b>" in out
        and "<b>?</b>" in out
        and "[nope x=1]" in out
        and 'title="[hello]"' in out
    )
    with pytest.raises(ShortcodeError, match="already answered by test"):
        registry.register("Hello", "other", lambda a, c: "")
    registry.register("boom", "test", lambda a, c: 1 / 0)
    assert str(registry.expand("a [boom] b")) == "a  b"  # a failing shortcode renders nothing


# --- types -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("types", "taxonomies", "message"),
    [
        ({"x": {"title": "X", "path": "/{nope}/{slug}/"}}, {}, "unknown path tokens"),
        ({"x": {"title": "X", "path": "/x/"}}, {}, "needs {slug} or {path}"),
        ({"x": {"title": "X", "fields": {"k": {"type": "select"}}}}, {}, "select without choices"),
        ({"x": {"title": "X", "taxonomies": ["cat"]}}, {}, "undeclared taxonomies"),
        ({"x": {"title": "X", "colour": "red"}}, {}, "Extra inputs"),
    ],
)
def test_bad_types_are_refused(types, taxonomies, message):
    with pytest.raises(TypesError, match=message):
        Registry.from_sections([("app", types)], [("app", taxonomies)])


def test_paths_from_templates():
    from datetime import datetime

    when = datetime(2026, 11, 13)
    assert (
        build_path(
            "/{category}/{slug}/",
            slug="b",
            entry_id=1,
            type_name="post",
            category="istorie/biserici",
            when=when,
        )
        == "/istorie/biserici/b/"
    )
    assert (
        build_path("/{path}/", slug="c", entry_id=1, type_name="page", parent_path="a/b")
        == "/a/b/c/"
    )
    assert (
        build_path("/e/{year}/{month}/{slug}/", slug="x", entry_id=1, type_name="e", when=when)
        == "/e/2026/11/x/"
    )


# --- moving WordPress in ---------------------------------------------------------------


def test_wordpress_comes_in_with_its_addresses(wordpress):
    r = wordpress.report
    assert (r.terms, r.entries, r.media, r.files, r.menus) == (3, 5, 1, 1, 1)
    assert any("bwg_gallery" in s for s in r.skipped)
    c = wordpress
    page = c.get(
        "/despre-sat/biserici/biserica-din-sat/"
    )  # /%category%/%postname%/, parent included
    assert page.status_code == 200
    assert "<p>Biserica a fost ridicată în 1791.</p>" in page.text  # wpautop
    # an old host, rewritten; shown at the widths a phone or a desk needs, loaded lazily
    body = page.text.split('<div class="body">', 1)[1]
    img = re.search(r"<img [^>]*>", body).group(0)
    assert 'src="/media/uploads/2012/12/biserica.jpg"' in img
    assert 'srcset="/media/uploads/2012/12/biserica.jpg?w=320 320w,' in img
    assert 'loading="lazy"' in img and "sizes=" in img
    assert "onerror" not in page.text and "alert('x')" not in page.text
    # the featured image, sized
    assert 'src="/media/uploads/2012/12/biserica.jpg?w=1280" srcset=' in page.text
    assert ">Biserici<" in page.text and ">istorie<" in page.text
    assert c.get("/media/uploads/2012/12/biserica.jpg").content == b"\xff\xd8 big"
    assert c.get("/media/uploads/2012/12/biserica-300x200.jpg").status_code == 200  # resized copy
    assert c.get("/media/uploads/2012/12/biserica-copy.jpg").status_code == 404  # not a copy


def test_wordpress_links_pages_menus_and_front_page(wordpress):
    c = wordpress
    asezarea = c.get("/despre-sat/asezarea/").text
    assert (
        '<a href="/biserici/biserica-din-sat/" rel="noopener">biserica</a>' in asezarea
    )  # made relative
    home = c.get("/").text
    assert "Bine ai venit!" in home  # the static front page
    assert '<a href="/category/despre-sat/">Despre sat</a>' in home
    assert re.search(r'<a href="/"[^>]*aria-current="page">Acasă</a>', home)  # the page you are on
    assert "Istoria" in home  # the child page, listed under its parent
    assert c.get("/prima-pagina/istoria/").status_code == 200
    assert c.get("/despre-sat/nepublicat/").status_code == 404  # a draft
    assert c.get("/?p=11", follow_redirects=False).headers["location"] == "/despre-sat/asezarea/"
    assert c.nest.settings.get("content.per_page") == 5


def test_category_pages_include_subcategories_and_catlist_lists_siblings(wordpress):
    c = wordpress
    listing = c.get("/category/despre-sat/").text
    assert "Biserica Ortodoxă din sat" in listing and "Așezarea" in listing
    assert "Nepublicat" not in listing
    page = c.get("/despre-sat/biserici/biserica-din-sat/").text
    assert (
        '<ul class="shortcode-list">' not in page
    )  # alone in its category: an empty list is nothing


def test_importing_again_updates(wordpress, tmp_path):
    c = wordpress
    again = import_dump(
        c.db, c.search, c.storage, c.types, tmp_path / "wp.sql", uploads=tmp_path / "uploads"
    )
    assert again.entries == 5
    assert service.counts_by_type(c.db) == {"post": 3, "page": 2}


def test_rewrite():
    assert (
        rewrite('<img src="https://satul.ro/wp-content/uploads/a.jpg">', ["http://satul.ro"])
        == '<img src="/media/uploads/a.jpg">'
    )
    assert rewrite('<a href="http://satul.ro/x/">', ["http://satul.ro"]) == '<a href="/x/">'
    assert (
        rewrite('<a href="http://other.ro/x/">', ["http://satul.ro"])
        == '<a href="http://other.ro/x/">'
    )


# --- serving ---------------------------------------------------------------------------


def test_paths_without_their_slash_redirect_and_unknown_ones_are_404(wordpress):
    c = wordpress
    r = c.get("/despre-sat/asezarea", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (301, "/despre-sat/asezarea/")
    page = c.get("/nu/exista/", headers={"Accept": "text/html"})
    assert page.status_code == 404 and "Pagina nu există." in page.text
    assert c.get("/nu/exista/").json() == {"detail": "Not Found"}


def test_media_is_never_a_page(site):
    site.storage.put("uploads/evil.svg", b"<svg onload=alert(1)>")
    site.storage.put("uploads/evil.html", b"<script>x</script>")
    for key in ("uploads/evil.svg", "uploads/evil.html"):
        r = site.get(f"/media/{key}")
        assert r.headers["content-disposition"] == "attachment"
        assert "sandbox" in r.headers["content-security-policy"]
    assert site.get("/media/../data/app.db").status_code == 404
    assert site.get("/media/%2e%2e/data/secret.key").status_code == 404


@pytest.mark.parametrize("key", ["../x", "a/../b", "a//b", "a/\x00b", "", ".", "a/./b"])
def test_storage_keys_cannot_escape(key):
    with pytest.raises(StorageError):
        clean_key(key)


# --- editing ---------------------------------------------------------------------------


def test_an_editor_writes_an_entry_of_a_declared_type(site):
    sign_in(site)
    assert "Evenimente" in site.get("/admin/content/").text
    form = site.get("/admin/content/event/new").text
    assert 'name="field_starts"' in form and 'type="datetime-local"' in form and "nedeie" in form
    headers = {"X-CSRF-Token": site.cookies["nest_csrf"]}
    r = site.post(
        "/admin/content/event/new",
        headers={**headers, "HX-Request": "true"},
        data={
            "title": "Hramul satului",
            "status": "published",
            "field_seats": "many",
            "body": "<p>Vino!</p>",
        },
    )
    assert "field_starts" in r.text or "starts" in r.text  # a required field, reported
    r = site.post(
        "/admin/content/event/new",
        headers=headers,
        follow_redirects=False,
        data={
            "title": "Hramul satului",
            "status": "published",
            "published_at": "2026-08-15T10:00",
            "field_starts": "2026-08-15T10:00",
            "field_seats": "120",
            "field_kind": "hram",
            "body": "<p onclick='x'>Vino!</p><script>bad()</script>",
        },
    )
    assert r.status_code == 303
    page = site.get("/evenimente/2026/hramul-satului/")
    assert page.status_code == 200 and "<p>Vino!</p>" in page.text and "bad()" not in page.text
    e = service.entry_by_path(site.db, "/evenimente/2026/hramul-satului/")
    assert e.fields == {"starts": "2026-08-15T10:00:00", "seats": 120, "kind": "hram"}
    assert "hramul" in site.get("/search?q=hramul").text.lower()


def test_children_follow_their_parents_slug_and_revisions_are_kept(site):
    parent = service.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(type="page", title="Istorie", status="published"),
    )
    child = service.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(type="page", title="Biserica", status="published", parent_id=parent.id),
    )
    assert child.path == "/istorie/biserica/"
    for i in range(12):
        service.save_entry(
            site.db,
            site.search,
            site.types,
            EntryData(
                type="page",
                title="Istoria satului",
                slug="istoria-satului",
                status="published",
                body=f"v{i}",
            ),
            existing_id=parent.id,
        )
    assert service.entry(site.db, child.id).path == "/istoria-satului/biserica/"
    assert site.get("/istoria-satului/biserica/").status_code == 200
    assert len(service.revisions(site.db, parent.id)) == 10  # pruned to the type's limit


def test_only_editors_reach_the_editor(site):
    assert site.get("/admin/content/", follow_redirects=False).status_code == 303
    sign_in(site, roles=())
    assert site.get("/admin/content/").status_code == 403


def test_content_must_be_mounted_at_the_root(tmp_path):
    root = tmp_path / "bad"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP).replace("{name: content, route: /}", "{name: content, route: /cms}")
    )
    with pytest.raises(Exception, match="include it with route: /"):
        create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def test_a_leading_slash_stays_inside_the_store(site):
    assert clean_key("/etc/passwd") == "etc/passwd"
    assert Path(site.storage.local_path("/etc/passwd")).is_relative_to(site.storage.root)


def test_storage_round_trip(site, tmp_path):
    stat = site.storage.put("a/b.txt", b"hello")
    assert stat.size == 5 and site.storage.open("a/b.txt").read() == b"hello"
    assert list(site.storage.keys("a")) == ["a/b.txt"]
    site.storage.delete("a/b.txt")
    assert site.storage.stat("a/b.txt") is None
    assert (
        Path(site.storage.local_path("x.txt")).parent
        == Path(site.storage.local_path("y.txt")).parent
    )


def test_mysqldump_reads_tables_written_on_one_line():
    dump = Dump.parse(
        "CREATE TABLE `a` (`id` int, `kind` enum('Y','N'), `price` decimal(10,2), PRIMARY KEY (`id`)) ENGINE=InnoDB;\n"
        "INSERT INTO `a` VALUES (1,'Y',2.50);\n"
        "CREATE TABLE IF NOT EXISTS `b` (\n  `x` int,\n  KEY `k` (`x`)\n) DEFAULT CHARSET=utf8;\n"
        "INSERT INTO `b` VALUES (7);\n"
    )
    assert dump.columns == {"a": ["id", "kind", "price"], "b": ["x"]}
    assert list(dump.rows("a")) == [{"id": 1, "kind": "Y", "price": 2.5}]
    assert list(dump.rows("b")) == [{"x": 7}]


GETICUS = r"""
CREATE TABLE `settings` (`id` int, `slug` varchar(50), `value` text, `module` varchar(50)) ENGINE=InnoDB;
INSERT INTO `settings` VALUES (6,'site_homepage','19','content');
CREATE TABLE `categories` (
  `id` int, `category_group_id` int, `parent_id` int, `title` varchar(100), `url_title` varchar(100), `description` text, `sort` int
) ENGINE=InnoDB;
INSERT INTO `categories` VALUES (9,3,0,'Istorie','istorie',NULL,9);
CREATE TABLE `content_fields` (`id` int, `content_type_id` int, `content_field_type_id` int, `short_tag` varchar(50), `sort` int) ENGINE=InnoDB;
INSERT INTO `content_fields` VALUES (1,1,1,'main_column',2),(10,5,8,'logo',10);
CREATE TABLE `entries` (
  `id` int, `slug` varchar(100), `title` varchar(200), `content_type_id` int, `status` varchar(20), `created_date` int, `modified_date` int
) ENGINE=InnoDB;
INSERT INTO `entries` VALUES (19,NULL,'Acasa',1,'published',1424000000,1424000000),(21,'locomotive-cu-aburi','Locomotive cu aburi',1,'published',1424000000,1424000000),(4,'about','About',1,'published',1424000000,1424000000),(9,NULL,'Saa',1,'published',0,0),(10,NULL,'Template gara',5,'published',0,0),(20,'istoric','Istoric',1,'draft',0,0);
CREATE TABLE `entries_data` (`id` int, `entry_id` int, `field_id_1` text, `field_id_10` text) ENGINE=InnoDB;
INSERT INTO `entries_data` VALUES (1,19,'<p>Bine ai venit</p>',NULL),(2,21,'<p>Abur <img src=\"/assets/cms/uploads/images/loc/Abur%20mare.jpg\"><script>x</script></p>',NULL),(3,4,'<p>Despre</p>',NULL);
CREATE TABLE `categories_entries` (`id` int, `category_id` int, `entry_id` int) ENGINE=InnoDB;
INSERT INTO `categories_entries` VALUES (1,9,21),(2,0,4);
CREATE TABLE `navigation_items` (
  `id` int, `type` varchar(20), `language` varchar(20), `entry_id` int, `category_id` int, `component` varchar(50),
  `title` varchar(100), `url` varchar(200), `target` varchar(10), `parent_id` int, `hide` int, `sort` int, `parameters` text
) ENGINE=InnoDB;
INSERT INTO `navigation_items` VALUES (1,'category_list','romanian',0,9,'','Istorie','','',0,0,1,''),(2,'component','romanian',0,0,'mersultrenurilor','Gări','','',0,0,2,'a:3:{s:4:\"name\";s:4:\"gari\";s:9:\"real_name\";s:4:\"Gari\";}'),(3,'page','romanian',4,0,'','Despre','','',0,1,3,''),(4,'page','english',4,0,'','About','','',0,0,1,''),(5,'component','romanian',0,0,'contact','Contact','','',0,0,9,'');
"""


def test_a_geticus_site_comes_in_with_its_addresses(tmp_path):
    from nest_content.geticus import import_dump as import_geticus

    root = tmp_path / "gari"
    root.mkdir()
    manifest = textwrap.dedent(APP).replace(
        "content_types:\n  event:",
        """content_types:
  page: {title: Pagini, path: "/{path}", hierarchical: true}
  article: {title: Articole, path: "/cfr/{category}/{slug}", taxonomies: [category]}
taxonomies:
  category: {title: Categorii, hierarchical: true, path: "/cfr/{path}"}
unused_types:
  event:""",
    )
    (root / "module.yml").write_text(manifest, encoding="utf-8")
    site_dir = tmp_path / "site"
    (site_dir / "assets/cms/uploads/images/loc").mkdir(parents=True)
    (site_dir / "assets/cms/uploads/images/loc/Abur mare.jpg").write_bytes(b"jpeg")
    dump = tmp_path / "gari.sql"
    dump.write_text(GETICUS, encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    n = app.state.nest
    b = n.bindings
    types = n.module_state["content"]["types"]
    report = import_geticus(
        b.get("nest.db"),
        b.get("nest.search"),
        b.get("nest.storage"),
        types,
        dump,
        root=site_dir,
        settings=n.settings,
    )
    assert (report.terms, report.entries, report.files, report.menu_items) == (1, 4, 1, 2)
    assert any("Saa" in s for s in report.skipped) and any(
        "Template gara" in s for s in report.skipped
    )
    assert any(
        "Contact" in s for s in report.skipped
    )  # no such module here: reported, not linked to nothing
    with TestClient(app) as c:
        page = c.get("/cfr/istorie/locomotive-cu-aburi")
        assert (
            page.status_code == 200
            and ' src="/media/assets/cms/uploads/images/loc/Abur%20mare.jpg">' in page.text
            and "Abur%20mare.jpg?w=640 640w" in page.text
        )
        assert "<script>" not in page.text.split('<div class="body">')[1]
        assert c.get("/media/assets/cms/uploads/images/loc/Abur%20mare.jpg").content == b"jpeg"
        assert c.get("/cfr/istorie").status_code == 200 and c.get("/about").status_code == 200
        assert c.get("/istoric").status_code == 404  # a draft
        home = c.get("/").text
        assert "Bine ai venit" in home  # site_homepage
        assert (
            '<a href="/cfr/istorie">Istorie</a>' in home and '<a href="/cfr/gari">Gări</a>' in home
        )
        assert "About" not in home  # the English menu, and a hidden item, left
        again = import_geticus(
            b.get("nest.db"),
            b.get("nest.search"),
            b.get("nest.storage"),
            types,
            dump,
            root=site_dir,
        )
        assert again.entries == 4
        assert service.counts_by_type(b.get("nest.db")) == {"page": 3, "article": 1}


# --- what search engines, feed readers and shared links see -------------------------


def test_sitemap_feed_and_robots(wordpress):
    c = wordpress
    sitemap = c.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "<loc>http://testserver/despre-sat/biserici/biserica-din-sat/</loc>" in sitemap.text
    assert "<loc>http://testserver/category/despre-sat/biserici/</loc>" in sitemap.text
    assert "<lastmod>" in sitemap.text
    c.nest.settings.set("content.site_url", "https://satul.ro/")
    assert "<loc>https://satul.ro/</loc>" in c.get("/sitemap.xml").text
    feed = c.get("/feed/")
    assert feed.headers["content-type"].startswith("application/rss+xml")
    assert "<title>Biserica Ortodoxă din sat</title>" in feed.text
    assert "<link>https://satul.ro/despre-sat/biserici/biserica-din-sat/</link>" in feed.text
    assert c.get("/feed", follow_redirects=False).headers["location"] == "/feed/"
    robots = c.get("/robots.txt").text
    assert "Disallow: /\n" in robots or robots.rstrip().endswith("Disallow: /")  # not production
    c.nest.production = True
    robots = c.get("/robots.txt").text
    assert "Disallow: /admin/" in robots and "Disallow: /cont/" in robots
    assert "Sitemap: https://satul.ro/sitemap.xml" in robots


def test_a_page_tells_what_it_is_when_shared(wordpress):
    page = wordpress.get("/despre-sat/biserici/biserica-din-sat/").text
    assert (
        '<link rel="canonical" href="http://testserver/despre-sat/biserici/biserica-din-sat/">'
        in page
    )
    assert '<meta property="og:title" content="Biserica Ortodoxă din sat">' in page
    assert '<meta property="og:type" content="article">' in page
    assert 'og:image" content="http://testserver/media/uploads/2012/12/biserica.jpg?w=1280"' in page
    assert '<meta name="description" content="Biserica a fost ridicată în 1791.' in page
    assert 'type="application/rss+xml"' in page


def test_a_youtube_address_alone_is_a_video_that_loads_when_played(site):
    service.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="page",
            title="Obiceiuri",
            status="published",
            body=(
                "<p>Colindul:</p><div>https://www.youtube.com/watch?v=c6oLgc9Jujo<span>&nbsp;</span></div>"
                '<p>Vezi <a href="https://youtu.be/leY6NPTOXCo">aici</a> în text.</p>'
                '<p>[youtube url="https://youtu.be/CjNXyVl0IVk"]</p>'
            ),
        ),
    )
    r = site.get("/obiceiuri/")
    assert r.text.count('class="video"') == 2
    assert 'data-video="c6oLgc9Jujo"' in r.text and 'data-video="CjNXyVl0IVk"' in r.text
    assert 'href="https://youtu.be/leY6NPTOXCo"' in r.text  # a link in a sentence stays one
    assert 'data-video="leY6NPTOXCo"' not in r.text
    assert "Pornește filmul" in r.text and "content/video.js" in r.text
    assert "<iframe" not in r.text  # nothing asks YouTube for anything until it is played
    assert (
        "frame-src 'self' https://www.youtube-nocookie.com" in r.headers["content-security-policy"]
    )


def test_pictures_are_made_at_the_widths_pages_ask_for(site):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (2400, 1600), "olive").save(out, "JPEG")
    site.storage.put("poze/sat.jpg", out.getvalue(), "image/jpeg")
    site.storage.put("acte/act.pdf", b"%PDF-1.4", "application/pdf")
    r = site.get("/media/poze/sat.jpg?w=600")  # taken up to the next width media makes
    assert r.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(r.content)).size == (640, 427)
    assert site.storage.stat("_sized/640/poze/sat.jpg.webp") is not None  # kept
    assert site.get("/media/poze/sat.jpg?w=99999").headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(site.get("/media/poze/sat.jpg?w=99999").content)).width == 1920
    assert site.get("/media/poze/sat.jpg").headers["content-type"] == "image/jpeg"  # as stored
    assert site.get("/media/acte/act.pdf?w=640").content == b"%PDF-1.4"  # not a picture
    assert site.get("/media/poze/sat.jpg?w=abc").status_code == 422


# --- the editor: its page, its pictures ---------------------------------------------


def _png(width=4, height=3):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, "PNG")
    return out.getvalue()


def test_the_edit_page_has_the_editor(site):
    sign_in(site)
    page = site.get("/admin/content/post/new").text
    assert "content/editor/editor.js" in page and "content/editor/editor.css" in page
    assert 'name="body"' in page and "data-editor" in page  # still the textarea, posted as before
    assert 'data-media-list="/admin/content/media.json"' in page
    assert (
        "&#34;bold&#34;: &#34;\\u00cengro\\u0219at&#34;" in page
    )  # its words, in the site's language


def test_an_editor_uploads_a_picture_and_finds_it_in_the_library(site):
    sign_in(site)
    csrf = {"x-csrf-token": site.cookies["nest_csrf"]}
    r = site.post(
        "/admin/content/media",
        files={"file": ("Biserica de lemn.PNG", _png(), "application/octet-stream")},
        data={"alt": "Biserica"},
        headers=csrf,
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["key"].startswith("uploads/") and item["key"].endswith("/biserica-de-lemn.png")
    assert item["thumb"].endswith("?w=320") and item["alt"] == "Biserica"
    again = site.post(
        "/admin/content/media",
        files={"file": ("biserica de lemn.png", _png(), "image/png")},
        headers=csrf,
    ).json()
    assert again["key"].endswith("/biserica-de-lemn-2.png")  # never over another
    assert site.get(item["url"]).headers["content-type"] == "image/png"
    found = site.get("/admin/content/media.json?q=biserica").json()["items"]
    assert [i["key"] for i in found] == [again["key"], item["key"]]  # newest first
    fake = site.post(
        "/admin/content/media",
        files={"file": ("poza.png", b"<svg onload=alert(1)>", "image/png")},
        headers=csrf,
    )
    assert fake.status_code == 415 and "JPEG" in fake.json()["error"]  # by its bytes, not its name
    site.nest.settings.set("content.media_max_mb", 1)
    big = site.post(
        "/admin/content/media",
        files={"file": ("mare.png", _png() + b"\0" * (2**20 + 10), "image/png")},
        headers=csrf,
    )
    assert big.status_code == 413
    no_token = site.post("/admin/content/media", files={"file": ("a.png", _png(), "image/png")})
    assert no_token.status_code == 403


def test_only_editors_reach_the_library(site):
    assert site.get("/admin/content/media.json", follow_redirects=False).status_code in (
        303,
        401,
        403,
    )
    r = site.post(
        "/admin/content/media",
        files={"file": ("a.png", _png(), "image/png")},
        headers={"x-csrf-token": site.cookies.get("nest_csrf", "")},
        follow_redirects=False,
    )
    assert r.status_code in (303, 401, 403)


# --- versions and the trash ---------------------------------------------------------


def _write(site, title, body, existing=None, status="published"):
    return service.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(type="page", title=title, status=status, body=body),
        existing_id=existing,
    )


def test_a_version_shows_what_changed_and_comes_back(site):
    sign_in(site)
    e = _write(site, "Istoria", "<p>Satul e vechi.</p><p>Biserica e din 1838.</p>")
    _write(
        site, "Istoria satului <b>", "<p>Satul e foarte vechi.</p><p>Biserica e din 1838.</p>", e.id
    )
    first, *_ = reversed(service.revisions(site.db, e.id))  # the oldest: as it was written
    page = site.get(f"/admin/content/page/{e.id}/versions/{first.id}")
    assert page.status_code == 200
    assert "Satul e <ins>foarte</ins> vechi." in page.text
    assert '<p class="diff-same">Biserica e din 1838.</p>' in page.text
    preview = page.text.split('class="entry version-preview', 1)[1]
    assert "<p>Satul e vechi.</p>" in preview and "&lt;p&gt;" not in preview  # shown, formatted
    assert "<del>Istoria</del>" in page.text and "<ins>Istoria satului &lt;b&gt;</ins>" in page.text

    csrf = site.cookies["nest_csrf"]
    r = site.post(
        f"/admin/content/page/{e.id}/versions/{first.id}/restore",
        data={"csrf_token": csrf, "what": "all"},
    )
    assert r.status_code == 200
    now = service.entry(site.db, e.id)
    assert (now.title, now.body) == ("Istoria", "<p>Satul e vechi.</p><p>Biserica e din 1838.</p>")
    undo = service.revisions(site.db, e.id)[0]  # the version the restore replaced
    assert undo.data["title"] == "Istoria satului <b>"
    site.post(
        f"/admin/content/page/{e.id}/versions/{undo.id}/restore",
        data={"csrf_token": csrf, "what": "text"},
    )
    now = service.entry(site.db, e.id)
    assert now.title == "Istoria" and "foarte vechi" in now.body  # only the text came back


def test_a_version_opens_in_the_editor_as_an_unsaved_copy(site):
    sign_in(site)
    e = _write(site, "Portul", "<p>Ie cu altiță.</p>")
    _write(site, "Portul popular", "<p>Ie.</p>", e.id)
    old = service.revisions(site.db, e.id)[0]
    page = site.get(f"/admin/content/page/{e.id}?from_version={old.id}").text
    assert 'value="Portul"' in page and "Ie cu altiță." in page and "Lucrezi pe o copie" in page
    assert service.entry(site.db, e.id).title == "Portul popular"  # nothing changed until saved


def test_deleting_puts_it_in_the_trash_and_it_comes_back_as_it_was(site):
    sign_in(site)
    csrf = site.cookies["nest_csrf"]
    e = _write(site, "Tradiții", "<p>Nedeia.</p>")
    assert site.get("/traditii/").status_code == 200
    site.post(f"/admin/content/page/{e.id}/delete", data={"csrf_token": csrf})
    assert service.entry(site.db, e.id).status == "trash"
    assert site.get("/traditii/").status_code == 404
    assert "Tradiții" not in site.get("/admin/content/page").text.split("<tbody>")[1]
    assert "Coș (1)" in site.get("/admin/content/page").text
    assert "Tradiții" in site.get("/admin/content/page/trash").text
    assert site.search.query("Nedeia", kind=service.KIND) == []
    with pytest.raises(service.ContentError, match="trash"):
        _write(site, "Tradiții", "<p>altfel</p>", e.id)
    assert (
        site.post(f"/admin/content/page/{e.id}/untrash", data={"csrf_token": csrf}).status_code
        == 200
    )
    back = service.entry(site.db, e.id)
    assert back.status == "published" and site.get("/traditii/").status_code == 200
    assert site.search.query("Nedeia", kind=service.KIND)


def test_only_what_is_in_the_trash_is_deleted_for_good_and_it_empties_itself(site):
    sign_in(site)
    csrf = site.cookies["nest_csrf"]
    keep = _write(site, "Rămâne", "<p>a</p>")
    gone = _write(site, "Pleacă", "<p>b</p>")
    assert (
        site.post(f"/admin/content/page/{keep.id}/purge", data={"csrf_token": csrf}).status_code
        == 404
    )
    service.trash_entry(site.db, site.search, gone.id)
    assert service.empty_trash(site.db, site.search, older_than_days=30) == 0  # not old enough
    site.post(f"/admin/content/page/{gone.id}/purge", data={"csrf_token": csrf})
    assert service.entry(site.db, gone.id) is None and service.revisions(site.db, gone.id) == []
    assert service.entry(site.db, keep.id) is not None


def test_a_long_unchanged_stretch_folds_and_pictures_are_named():
    from nest_content.diff import text_diff

    same = "".join(f"<p>Rând {i}.</p>" for i in range(8))
    shown, changed = text_diff(
        same + '<p>Vechi.</p><img src="/media/a.jpg" alt="Biserica">',
        same + "<p>Nou.</p>",
        picture="imagine",
        unchanged=lambda n: f"{n} neschimbate",
    )
    assert changed == 2 and "… 6 neschimbate …" in shown
    assert "Rând 0." in shown and "Rând 7." in shown and "Rând 3." not in shown
    assert "<del>[imagine: Biserica]</del>" in shown
