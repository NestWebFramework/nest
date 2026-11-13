"""The gallery module: on its own, inside content pages, and moved in from WordPress plugins."""

import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_gallery import service
from nest_gallery.wordpress import import_dump

from nest import create_app

ALONE = """
module: {name: photos, id: test.app.photos, type: application, version: 0.1.0}
application: {title: Foto, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.storage: {providers: [storage-local]}
"""

WITH_CONTENT = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: content, route: /}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
"""

DUMP = r"""
CREATE TABLE `wp_posts` (
  `ID` bigint(20),
  `post_content` longtext,
  `post_title` text,
  `post_status` varchar(20),
  `post_name` varchar(200),
  `post_type` varchar(20)
) ENGINE=InnoDB;
INSERT INTO `wp_posts` VALUES (115,'[Best_Wordpress_Gallery id=\"2\" gal_title=\"Foto\"]','Fotografii','publish','fotografii','page'),(116,'[nggallery id=1]','Vechi','publish','vechi','page'),(117,'[Best_Wordpress_Gallery id=\"9\"]','Ciornă','draft','ciorna','page');
CREATE TABLE `wp_bwg_shortcode` (
  `id` bigint(20),
  `tagtext` mediumtext
) ENGINE=InnoDB;
INSERT INTO `wp_bwg_shortcode` VALUES (2,' gallery_type=\"album_extended_preview\" album_id=\"1\"'),(3,' type=\"gallery\" gallery_id=\"1\"'),(9,' type=\"gallery\" gallery_id=\"3\"');
CREATE TABLE `wp_bwg_gallery` (
  `id` bigint(20),
  `name` varchar(255),
  `slug` varchar(255),
  `description` mediumtext,
  `preview_image` mediumtext,
  `random_preview_image` mediumtext,
  `order` bigint(20),
  `published` tinyint(1)
) ENGINE=InnoDB;
INSERT INTO `wp_bwg_gallery` VALUES (1,'De prin sat','de-prin-sat','','','/din_sat/thumb/a.jpg',1,1),(2,'Hramul','hramul','La biserică','','',2,1),(3,'Nefolosită','nefolosita','','','',3,1);
CREATE TABLE `wp_bwg_album` (
  `id` bigint(20),
  `name` varchar(255),
  `slug` varchar(255),
  `description` mediumtext,
  `order` bigint(20),
  `published` tinyint(1)
) ENGINE=InnoDB;
INSERT INTO `wp_bwg_album` VALUES (1,'Fotografii vechi si noi','fotografii-vechi-si-noi','',1,1);
CREATE TABLE `wp_bwg_album_gallery` (
  `id` bigint(20),
  `album_id` bigint(20),
  `is_album` tinyint(1),
  `alb_gal_id` bigint(20),
  `order` bigint(20)
) ENGINE=InnoDB;
INSERT INTO `wp_bwg_album_gallery` VALUES (5,1,0,2,1),(6,1,0,1,2);
CREATE TABLE `wp_bwg_image` (
  `id` bigint(20),
  `gallery_id` bigint(20),
  `image_url` mediumtext,
  `thumb_url` mediumtext,
  `description` mediumtext,
  `alt` mediumtext,
  `order` bigint(20),
  `published` tinyint(1)
) ENGINE=InnoDB;
INSERT INTO `wp_bwg_image` VALUES (1,1,'/din_sat/a.jpg','/din_sat/thumb/a.jpg','Ulița <b>mare</b>','ulita',2,1),(2,1,'/din_sat/b.jpg','/din_sat/thumb/b.jpg','','',1,1),(3,2,'/hram/c.jpg','/hram/thumb/c.jpg','','',1,1),(4,2,'/hram/lipsa.jpg','/hram/thumb/lipsa.jpg','','',2,1),(5,1,'/din_sat/ascunsa.jpg','','','',3,0);
CREATE TABLE `wp_ngg_gallery` (
  `gid` bigint(20),
  `name` varchar(255),
  `path` mediumtext,
  `title` mediumtext,
  `galdesc` mediumtext
) ENGINE=InnoDB;
INSERT INTO `wp_ngg_gallery` VALUES (1,'vechi','/wp-content/gallery/vechi','Fotografii vechi','');
CREATE TABLE `wp_ngg_pictures` (
  `pid` bigint(20),
  `galleryid` bigint(20),
  `filename` varchar(255),
  `description` mediumtext,
  `alttext` mediumtext,
  `exclude` tinyint(4),
  `sortorder` bigint(20)
) ENGINE=InnoDB;
INSERT INTO `wp_ngg_pictures` VALUES (1,1,'x.jpg','','x',0,0),(2,1,'y.jpg','','y',1,0);
"""


def make(tmp_path, manifest: str) -> TestClient:
    root = tmp_path / "app"
    root.mkdir(exist_ok=True)
    (root / "module.yml").write_text(textwrap.dedent(manifest), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    c = TestClient(app)
    c.db, c.storage = (app.state.nest.bindings.get(k) for k in ("nest.db", "nest.storage"))
    return c


def wordpress_folder(tmp_path):
    wp = tmp_path / "wp"
    files = [
        "wp-content/uploads/photo-gallery/din_sat/a.jpg",
        "wp-content/uploads/photo-gallery/din_sat/b.jpg",
        "wp-content/uploads/photo-gallery/din_sat/thumb/a.jpg",
        "wp-content/uploads/photo-gallery/din_sat/thumb/b.jpg",
        "wp-content/uploads/photo-gallery/hram/c.jpg",
        "wp-content/uploads/photo-gallery/hram/thumb/c.jpg",
        "wp-content/gallery/vechi/x.jpg",
        "wp-content/gallery/vechi/thumbs/thumbs_x.jpg",
    ]
    for f in files:
        (wp / f).parent.mkdir(parents=True, exist_ok=True)
        (wp / f).write_bytes(f.encode())
    dump = tmp_path / "wp.sql"
    dump.write_text(DUMP, encoding="utf-8")
    return dump, wp / "wp-content" / "uploads"


def test_a_gallery_application_without_content(tmp_path):
    with make(tmp_path, ALONE) as c:
        album = service.ensure(c.db, "Vara 2026")
        g = service.ensure(c.db, "La munte", parent_id=album.id)
        c.storage.put("foto/a.jpg", b"jpeg")
        service.set_photos(
            c.db, g.id, [{"key": "foto/a.jpg", "caption": "Vlădeasa", "alt": "munte"}]
        )
        index = c.get("/galerii/").text
        assert 'href="/galerii/vara-2026/"' in index and "1 galerie" in index
        page = c.get("/galerii/la-munte/").text
        assert (
            'href="/media/foto/a.jpg" data-lightbox="g' in page
            and 'data-caption="Vlădeasa"' in page
        )
        assert 'alt="munte"' in page and "lightbox.js" in page
        assert c.get("/media/foto/a.jpg").content == b"jpeg"
        assert c.get("/galerii/nu-exista/").status_code == 404


def test_wordpress_galleries_come_in_and_old_shortcodes_keep_working(tmp_path):
    dump, uploads = wordpress_folder(tmp_path)
    with make(tmp_path, WITH_CONTENT) as c:
        report = import_dump(c.db, c.storage, dump, uploads=uploads)
        assert (report.galleries, report.albums) == (
            3,
            1,
        )  # two bwg galleries in the album, one ngg
        assert report.skipped == 1  # "Nefolosită": only a draft uses it
        assert report.photos == 4 and any("lipsa.jpg" in m for m in report.missing)
        assert [card.collection.slug for card in service.cards(c.db, None)] == [
            "vechi",
            "fotografii-vechi-si-noi",
        ]
        album = service.by_slug(c.db, "fotografii-vechi-si-noi")
        assert [x.collection.title for x in service.cards(c.db, album.id)] == [
            "Hramul",
            "De prin sat",
        ]
        photos = service.photos(c.db, service.by_slug(c.db, "de-prin-sat").id)
        assert [p.key for p in photos] == [
            "uploads/photo-gallery/din_sat/b.jpg",
            "uploads/photo-gallery/din_sat/a.jpg",
        ]
        assert photos[1].caption == "Ulița <b>mare</b>"  # text: escaped when shown

        from nest_content import service as content
        from nest_content.service import EntryData

        types = c.app.state.nest.module_state["content"]["types"]
        search = c.app.state.nest.bindings.get("nest.search")
        content.save_entry(
            c.db,
            search,
            types,
            EntryData(
                type="page",
                title="Fotografii",
                status="published",
                body='<p>[Best_Wordpress_Gallery id="2" gal_title="Foto"]</p>',
            ),
        )
        content.save_entry(
            c.db,
            search,
            types,
            EntryData(
                type="page", title="Vechi", status="published", body="<p>[nggallery id=1]</p>"
            ),
        )
        page = c.get("/fotografii/").text
        assert page.count('class="gallery-tile"') == 2 and "[Best_Wordpress_Gallery" not in page
        assert "gallery.css" in page
        gallery_page = c.get("/galerii/de-prin-sat/").text
        assert "Ulița &lt;b&gt;mare&lt;/b&gt;" in gallery_page
        vechi = c.get("/vechi/").text
        assert (
            'href="/media/wp-content/gallery/vechi/x.jpg"' in vechi and "y.jpg" not in vechi
        )  # excluded


def test_importing_galleries_again_changes_nothing(tmp_path):
    dump, uploads = wordpress_folder(tmp_path)
    with make(tmp_path, ALONE) as c:
        import_dump(c.db, c.storage, dump, uploads=uploads)
        again = import_dump(c.db, c.storage, dump, uploads=uploads)
        assert (again.galleries, again.photos) == (3, 4)
        assert len(service.cards(c.db, None)) == 2


def test_everything_moves_unused_galleries_too(tmp_path):
    dump, uploads = wordpress_folder(tmp_path)
    with make(tmp_path, ALONE) as c:
        report = import_dump(c.db, c.storage, dump, uploads=uploads, everything=True)
        assert report.galleries == 4 and report.skipped == 0


def test_the_gallery_module_answers_gallery_when_present(tmp_path):
    with make(tmp_path, WITH_CONTENT) as c:
        owner = c.app.state.nest.shortcodes._handlers["gallery"][0]
        assert owner == "gallery"
        assert {"album", "best_wordpress_gallery", "nggallery", "catlist"} <= set(
            c.app.state.nest.shortcodes.names()
        )


@pytest.mark.parametrize("missing", ["nefolosita", "nu-exista"])
def test_a_shortcode_for_nothing_renders_nothing(tmp_path, missing):
    with make(tmp_path, WITH_CONTENT) as c:
        out = str(c.app.state.nest.shortcodes.expand(f'<p>[gallery slug="{missing}"]</p>', None))
        assert re.fullmatch(r"<p>\s*</p>", out)


def test_albums_inside_albums_come_in_with_their_galleries(tmp_path):
    """transilpedia: a page shows album 4, which holds albums, which hold the galleries."""
    dump, uploads = wordpress_folder(tmp_path)
    nested = (
        DUMP.replace(
            "INSERT INTO `wp_bwg_album` VALUES (1,'Fotografii vechi si noi','fotografii-vechi-si-noi','',1,1);",
            "INSERT INTO `wp_bwg_album` VALUES (1,'Fotografii vechi si noi','fotografii-vechi-si-noi','',1,1),"
            "(4,'Transilvania','transilvania','',4,1);",
        )
        .replace(
            "INSERT INTO `wp_bwg_album_gallery` VALUES (5,1,0,2,1),(6,1,0,1,2);",
            "INSERT INTO `wp_bwg_album_gallery` VALUES (5,1,0,2,1),(6,1,0,1,2),(7,4,1,1,1),(8,4,0,3,2);",
        )
        .replace(
            '(2,\' gallery_type=\\"album_extended_preview\\" album_id=\\"1\\"\')',
            '(2,\' gallery_type=\\"album_extended_preview\\" album_id=\\"4\\"\')',
        )
    )
    assert nested != DUMP
    dump.write_text(nested, encoding="utf-8")
    with make(tmp_path, ALONE) as c:
        report = import_dump(c.db, c.storage, dump, uploads=uploads)
        assert (report.albums, report.skipped) == (2, 0)  # "Nefolosită" is in album 4 now
        top = service.cards(c.db, None)
        assert [x.collection.slug for x in top] == ["vechi", "transilvania"]
        transilvania = top[1]
        assert transilvania.is_album and transilvania.count == 2
        # An album has no photos of its own: its cover is its first child's.
        assert (
            transilvania.cover == "uploads/photo-gallery/hram/thumb/c.jpg"
        )  # via album 1, whose first is Hramul
        inner = service.cards(c.db, transilvania.collection.id)
        assert [x.collection.slug for x in inner] == ["fotografii-vechi-si-noi", "nefolosita"]
        assert service.by_alias(c.db, "bwg_shortcode", 2).slug == "transilvania"


def test_a_site_page_can_keep_the_gallery_route(tmp_path):
    manifest = ALONE.replace(
        "  - {name: gallery, route: /galerii}",
        "  - name: gallery\n    route: /galerii\n    config: {index: false}",
    )
    with make(tmp_path, manifest) as c:
        service.ensure(c.db, "Vara")
        assert c.get("/galerii/").status_code == 404  # left to whatever page the site has there
        assert c.get("/galerii/vara/").status_code == 200
