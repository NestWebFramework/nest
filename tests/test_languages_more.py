"""SEO, galleries and maps in two languages (Romanian at /, English at /en/).

What editors tell search engines about a page is kept per language; a translated page
without its own search words uses its translated text, never the Romanian. Galleries
and maps show their English words at their English addresses, the Romanian standing in
where there are none yet.
"""

import re
import textwrap
from html import unescape

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_gallery import service as gallery
from nest_maps import service as maps
from nest_maps.service import MapData, MarkerData
from nest_seo.models import MetaText

from nest import create_app

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro, en], language_urls: prefix, browser_language: false}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: translations}
  - {name: seo, config: {site_url: "https://sat.ro", description: "Satul de sub munte."}}
  - {name: gallery, route: /galerii}
  - {name: maps, route: /harta}
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
    c = TestClient(app, follow_redirects=False)
    with c:
        c.db = app.state.nest.bindings.get("nest.db")
        c.nest = app.state.nest
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


def translate(site, subject, owner_id, **english):
    form = {
        "csrf_token": site.csrf,
        "lang": "en",
        "tr_en_present": "1",
        "tr_en_status": "published",
    }
    form |= {f"tr_en_{k}": v for k, v in english.items()}
    r = site.post(f"/admin/translations/{subject}/{owner_id}", data=form)
    assert r.status_code == 303, r.text


def page(site, ro_title, english=None, **seo):
    data = {
        "csrf_token": site.csrf,
        "title": ro_title,
        "slug": "",
        "status": "published",
        "excerpt": "",
        "body": "<p>Text românesc.</p>",
    }
    if seo:
        data |= {"seo_present": "1"} | {f"seo_{k}": v for k, v in seo.items()}
    if english:
        data |= {"tr_en_present": "1", "tr_en_status": "published"} | {
            f"tr_en_{k}": v for k, v in english.items()
        }
    r = site.post("/admin/content/page/new", data=data)
    assert r.status_code == 303, r.text
    return int(re.search(r"/page/(\d+)", r.headers["location"]).group(1))


def head(html, name):
    m = re.search(rf'<meta (?:name|property)="{name}" content="([^"]*)"', html)
    return unescape(m.group(1)) if m else None


def test_search_words_are_said_in_each_language(site):
    eid = page(
        site,
        "Istoric",
        {"title": "History", "slug": "history", "excerpt": "The village's past."},
        title="Istoria satului",
        description="Trecutul satului.",
        canonical="/istoric/",
    )
    with site.db.session() as s:
        assert (
            s.get(MetaText, (f"content.entry:{eid}", "ro")).title == "Istoria satului"
        )  # the source
    ro = site.get("/istoric/").text
    assert "<title>Istoria satului" in ro and head(ro, "description") == "Trecutul satului."
    # the English page, before its search words are translated: its own English words
    en = site.get("/en/history/").text
    assert "Istoria satului" not in en and "Trecutul satului." not in en
    assert head(en, "description") == "The village's past." and "<title>History" in en
    assert head(en, "og:locale") == "en_US"
    assert (
        '<link rel="canonical" href="https://sat.ro/en/history/">' in en
    )  # its own, not the Romanian override
    # then translated in the translations module
    translate(
        site,
        "seo.meta",
        f"content.entry:{eid}",
        title="The village's history",
        description="Where the village comes from.",
        keywords="history, village",
    )
    en = site.get("/en/history/").text
    assert "<title>The village&#39;s history" in en or "<title>The village's history" in en
    assert (
        head(en, "description") == "Where the village comes from."
        and head(en, "keywords") == "history, village"
    )
    assert "<title>Istoria satului" in site.get("/istoric/").text


def test_an_untranslated_page_keeps_its_romanian_search_words(site):
    page(site, "Moara", title="Moara satului", description="Moara de apă.")
    en = site.get("/en/moara/").text
    assert "<title>Moara satului" in en and head(en, "description") == "Moara de apă."
    assert '<link rel="canonical" href="https://sat.ro/moara/">' in en


def test_the_site_description_is_not_put_on_english_pages(site):
    page(site, "Acasă", {"title": "Home", "slug": "home"})
    assert head(site.get("/acasa/").text, "description") in (
        "Satul de sub munte.",
        "Text românesc.",
    )
    assert head(site.get("/en/home/").text, "description") != "Satul de sub munte."


def test_a_gallery_in_english(site):
    c = gallery.ensure(site.db, "Iarna în sat", description="Fotografii de iarnă.")
    gallery.set_photos(
        site.db,
        c.id,
        [
            {"key": "a.jpg", "caption": "Biserica sub zăpadă", "alt": "Biserica"},
            {"key": "b.jpg", "alt": "IMG_2041.jpg"},
        ],
    )
    photos = gallery.photos(site.db, c.id)
    translate(
        site,
        "gallery.collection",
        c.id,
        title="Winter in the village",
        description="Winter photos.",
    )
    translate(
        site, "gallery.photo", photos[0].id, caption="The church under snow", alt="The church"
    )
    en = site.get("/en/galerii/iarna-in-sat/").text
    assert "Winter in the village" in en and "Winter photos." in en
    assert 'data-caption="The church under snow"' in en and 'alt="The church"' in en
    assert "Iarna în sat" in site.get("/galerii/iarna-in-sat/").text
    # a photo whose only words are a file name has nothing to translate
    states = site.nest.lookup(
        "translations.states", {"subject": "gallery.photo", "ids": [p.id for p in photos]}
    )
    assert list(states) == [photos[0].id]
    # the sitemap lists it at its English address
    assert "https://sat.ro/en/galerii/iarna-in-sat/" in site.get("/sitemap.xml").text


def test_an_untranslated_gallery_stands_in_and_says_so(site):
    gallery.ensure(site.db, "Vara")
    en = site.get("/en/galerii/vara/").text
    assert "Vara" in en
    hreflangs = re.findall(r'<link rel="alternate" hreflang="([^"]+)"', en)
    assert "en" not in hreflangs and "ro" in hreflangs


def test_a_map_in_english_and_its_markers_keep_their_translations(site):
    m = maps.save_map(
        site.db,
        MapData(
            title="Harta satului",
            slug="sat",
            lat=46.6,
            lng=22.9,
            markers=[MarkerData(46.6, 22.9, "Fântâna", "/fantana/", "Apă rece.")],
        ),
    )
    marker = maps.markers(site.db, m.id)[0]
    translate(site, "maps.map", m.id, title="The village map")
    translate(site, "maps.marker", marker.id, title="The well", description="Cold water.")
    page_ = site.get("/en/harta/sat/").text
    assert 'data-map="/en/harta/sat.geojson"' in page_ and "The village map" in page_
    data = site.get("/en/harta/sat.geojson").json()
    props = data["features"][0]["properties"]
    assert (
        props["title"] == "The well"
        and props["description"] == "Cold water."
        and props["url"] == "/en/fantana/"
    )
    assert site.get("/harta/sat.geojson").json()["features"][0]["properties"]["title"] == "Fântâna"
    # saving the map again keeps each marker (and its English) where it was
    maps.save_map(
        site.db,
        MapData(
            title="Harta satului",
            slug="sat",
            lat=46.6,
            lng=22.9,
            markers=[
                MarkerData(46.6, 22.9, "Fântâna veche", "/fantana/", "Apă rece."),
                MarkerData(46.61, 22.91, "Moara"),
            ],
        ),
        m.id,
    )
    assert maps.markers(site.db, m.id)[0].id == marker.id
    states = site.nest.lookup("translations.states", {"subject": "maps.marker", "ids": [marker.id]})
    assert states == {marker.id: {"en": "outdated"}}  # its Romanian changed
