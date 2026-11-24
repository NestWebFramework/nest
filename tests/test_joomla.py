"""Moving a Joomla 1.5 site in: articles, the GMapFP map's places, efemerides, JoomGallery."""

import textwrap

from fastapi.testclient import TestClient
from nest_content import service
from nest_content.joomla import EVENT, PLACE, body_of, import_dump
from nest_gallery import service as galleries
from nest_gallery.joomgallery import import_dump as import_gallery

from nest import create_app

APP = """
module: {name: oras, id: test.app.oras, type: application, version: 0.1.0}
application: {title: Orașul, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
taxonomies:
  categorie: {title: Categorii, path: "/locuri/{slug}/"}
content_types:
  page: {title: Pagini, path: "/{slug}/"}
  loc:
    title: Locuri
    path: "/loc/{slug}/"
    taxonomies: [categorie]
    fields:
      address: {type: text}
      phone: {type: text}
      web: {type: url}
      hours: {type: textarea}
      lat: {type: decimal}
      lng: {type: decimal}
  efemeride:
    title: Astăzi în istorie
    path: "/istorie/{slug}/"
    fields:
      date: {type: date}
"""

DUMP = r"""
CREATE TABLE `jos_content` (
  `id` int(11) NOT NULL, `title` varchar(255) NOT NULL, `alias` varchar(255) NOT NULL,
  `introtext` mediumtext NOT NULL, `fulltext` mediumtext NOT NULL, `state` tinyint(3) NOT NULL,
  `created` datetime NOT NULL, `publish_up` datetime NOT NULL
);
INSERT INTO `jos_content` VALUES (3,'Transport','transport','<h2>Transport in comun</h2><p>{zoomin src=\"images/stories/cluj/ratuc.jpg\"}images/stories/cluj/ratuc_s.jpg{/zoomin}</p><p style=\"color: #000\">{gmapfp id=\"22\" zmap=\"14\"}</p><p>{mersultrenurilor id=\"32015\"}</p>','',1,'2012-08-26 12:32:43','2012-08-26 12:32:43'),(2,'__404__','404','Nu e aici.','',1,'2004-11-11 12:44:38','2004-11-11 12:44:38'),(12,'Ciornă','ciorna','x','',0,'2012-01-01 00:00:00','2012-01-01 00:00:00');
CREATE TABLE `jos_categories` (
  `id` int(11) NOT NULL, `title` varchar(255) NOT NULL, `alias` varchar(255) NOT NULL, `section` varchar(50) NOT NULL
);
INSERT INTO `jos_categories` VALUES (9,'Oficii postale','oficii-postale','com_gmapfp'),(19,'Orange shops','orange-shops','com_gmapfp'),(41,'Clujul de azi','clujul-de-azi','1');
CREATE TABLE `jos_gmapfp` (
  `id` int(11) NOT NULL, `nom` varchar(255) NOT NULL, `alias` varchar(255) NOT NULL,
  `adresse` varchar(255) NOT NULL, `adresse2` varchar(255) NOT NULL, `codepostal` varchar(20) NOT NULL,
  `tel` varchar(50) NOT NULL, `tel2` varchar(50) NOT NULL, `web` varchar(255) NOT NULL,
  `intro` mediumtext NOT NULL, `horaires_prix` mediumtext NOT NULL,
  `glng` varchar(20) NOT NULL, `glat` varchar(20) NOT NULL, `catid` int(11) NOT NULL, `published` tinyint(1) NOT NULL
);
INSERT INTO `jos_gmapfp` VALUES (7,'Oficiul Postal 4','oficiul-postal-4','Str. Petru Maior, nr. 6-8','','400790','0264/591665 ','','www.posta-romana.ro','<p><b>Persoana de contact: </b>Ana Popescu</p>\r\n<p><strong>Servicii:</strong> Mandat postal</p>','<p><b>Orar: </b>L-V: 08:00-20:00</p>','23.5857818','46.7674257',9,1),(8,'Orange Iulius','orange-iulius','Str. Alexandru Vaida Voevod','','','','','','','','23.62','46.77',19,1);
CREATE TABLE `jos_efemerides` (
  `id` int(11) NOT NULL, `title` varchar(255) NOT NULL, `historicdate` date NOT NULL,
  `description` text NOT NULL, `alias` varchar(255) NOT NULL, `published` tinyint(1) NOT NULL
);
INSERT INTO `jos_efemerides` VALUES (3,'Sinagoga Neologă','1887-09-04','<p>Se inaugurează sinagoga.</p>','sinagoga-neologa',1);
CREATE TABLE `jos_joomgallery_catg` (
  `cid` int(11) NOT NULL, `name` varchar(255) NOT NULL, `alias` varchar(255) NOT NULL, `parent` int(11) NOT NULL,
  `catpath` varchar(255) NOT NULL, `description` text NOT NULL, `published` tinyint(1) NOT NULL, `ordering` int(11) NOT NULL
);
INSERT INTO `jos_joomgallery_catg` VALUES (2,'Piata Mihai Viteazu','piata-mihai-viteazu',1,'clujul_de_ieri_1/piata_mihai_viteazu_2','<p>O plimbare in timp.</p>',1,6),(1,'Clujul de ieri','clujul-de-ieri',0,'clujul_de_ieri_1','<p>Clujul de altadata.</p>',1,3);
CREATE TABLE `jos_joomgallery` (
  `id` int(11) NOT NULL, `catid` int(11) NOT NULL, `imgtitle` varchar(255) NOT NULL, `imgtext` text NOT NULL,
  `imgfilename` varchar(255) NOT NULL, `imgthumbname` varchar(255) NOT NULL, `published` tinyint(1) NOT NULL,
  `hidden` tinyint(1) NOT NULL, `ordering` int(11) NOT NULL
);
INSERT INTO `jos_joomgallery` VALUES (1,2,'1859-vedere de pe cetatuie','<p>Piata Mihai Viteazu</p>','1859.jpg','1859.jpg',1,0,-1),(2,2,'1904-piata','Piata Mihai Viteazu','1904.jpg','1904.jpg',1,0,-3),(3,2,'lipsa','','lipsa.jpg','lipsa.jpg',1,0,-2);
"""


def _site(tmp_path):
    root = tmp_path / "oras"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    old = tmp_path / "public_html"
    (old / "images/stories/cluj").mkdir(parents=True)
    (old / "images/stories/cluj/ratuc.jpg").write_bytes(b"big map")
    (old / "images/stories/cluj/ratuc_s.jpg").write_bytes(b"small map")
    for folder in ("originals", "thumbnails"):
        d = old / "images/joomgallery" / folder / "clujul_de_ieri_1/piata_mihai_viteazu_2"
        d.mkdir(parents=True)
        for name in ("1859.jpg", "1904.jpg"):
            (d / name).write_bytes(f"{folder} {name}".encode())
    dump = tmp_path / "joomla.sql"
    dump.write_text(DUMP, encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    return app, dump, old


def _bring(app, dump, old):
    n = app.state.nest
    b = n.bindings
    return import_dump(
        b.get("nest.db"),
        b.get("nest.search"),
        b.get("nest.storage"),
        n.module_state["content"]["types"],
        dump,
        root=old,
        place_type="loc",
        place_taxonomy="categorie",
        skip_place_categories={19},
        event_type="efemeride",
    )


def test_plugin_tags_go_and_zoomin_is_a_picture_linking_to_the_big_one():
    body, files = body_of(
        '<p>{zoomin src="images/stories/a.jpg"}images/stories/a_s.jpg{/zoomin}</p><p>{vremea id="x"}</p>'
    )
    assert (
        body
        == '<p><a href="/media/uploads/stories/a.jpg"><img src="/media/uploads/stories/a_s.jpg" alt=""></a></p>'
    )
    assert files == ["stories/a.jpg", "stories/a_s.jpg"]


def test_a_joomla_site_comes_in_articles_places_and_days(tmp_path):
    app, dump, old = _site(tmp_path)
    with TestClient(app) as c:
        _a_joomla_site(app, dump, old, c)


def _a_joomla_site(app, dump, old, c):
    report = _bring(app, dump, old)
    assert (report.entries, report.places, report.terms, report.events, report.files) == (
        1,
        1,
        1,
        1,
        2,
    )
    assert any("404" in s for s in report.skipped) and any("orange" in s for s in report.skipped)
    db = app.state.nest.bindings.get("nest.db")
    post = service.entry_by_legacy(db, PLACE + 7)
    assert post.fields["address"] == "Str. Petru Maior, nr. 6-8"
    assert post.fields["web"] == "http://www.posta-romana.ro"
    assert post.fields["hours"] == "L-V: 08:00-20:00"
    assert float(post.fields["lat"]) == 46.7674257
    assert "Popescu" not in post.body and "Mandat postal" in post.body  # a person, not the place
    day = service.entry_by_legacy(db, EVENT + 3)
    assert str(day.fields["date"]) == "1887-09-04"
    page = c.get("/transport/")
    assert page.status_code == 200 and "/media/uploads/stories/cluj/ratuc.jpg" in page.text
    assert "{" not in page.text.split('<div class="body">')[1].split("</div>")[0]
    assert c.get("/media/uploads/stories/cluj/ratuc_s.jpg").content == b"small map"
    assert c.get("/loc/oficiul-postal-4/").status_code == 200
    assert c.get("/locuri/oficii-postale/").status_code == 200
    again = _bring(app, dump, old)  # again: the same entries, updated
    assert again.places == 1 and service.counts_by_type(db) == {"page": 1, "loc": 1, "efemeride": 1}


def test_joomgallery_comes_in_with_its_tree(tmp_path):
    app, dump, old = _site(tmp_path)
    n = app.state.nest
    db, storage = n.bindings.get("nest.db"), n.bindings.get("nest.storage")
    report = import_gallery(db, storage, dump, root=old)
    assert (report.galleries, report.photos) == (2, 2) and report.missing == [
        "clujul_de_ieri_1/piata_mihai_viteazu_2/lipsa.jpg"
    ]
    square = galleries.by_alias(db, "joomgallery", 2)
    assert square.parent_id == galleries.by_alias(db, "joomgallery", 1).id
    photos = galleries.photos(db, square.id)
    assert [p.caption for p in photos] == ["1859-vedere de pe cetatuie", "1904-piata"]
    assert photos[0].thumb.startswith("joomgallery/thumbnails/")
    assert storage.stat(photos[0].key) is not None


def test_a_subject_s_feed_with_its_pictures(tmp_path):
    app, dump, old = _site(tmp_path)
    with TestClient(app) as c:
        _bring(app, dump, old)
        feed = c.get("/feed/?q=Transport&titlu=1").text
        assert "<title>Transport</title>" in feed and feed.count("<item>") == 1
        assert (
            '<enclosure url="http://testserver/media/uploads/stories/cluj/ratuc_s.jpg?w=640"'
            in feed
        )
        assert c.get("/feed/?q=nimic&titlu=1").text.count("<item>") == 0
