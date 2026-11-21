"""Content in two languages: Romanian at /, English at /en/, with translated slugs.

Each entry's, category's and menu label's text is in a text table (one row per
language); editors write the English beside the Romanian (the translations module), the
English address is made from the English slugs, and a page not yet translated shows
the Romanian text at its English address, pointing search engines at the original.
"""

import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_content import service
from nest_content.models import EntryText
from nest_content.service import EntryData
from sqlalchemy import delete, select

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
  - {name: redirects}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
"""


def start(root, ws):
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(ws)})
    c = TestClient(app, follow_redirects=False)
    c.__enter__()
    n = app.state.nest
    c.nest = n
    c.db, c.search = n.bindings.get("nest.db"), n.bindings.get("nest.search")
    c.types = n.module_state["content"]["types"]
    return c


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    return root


@pytest.fixture
def site(root, tmp_path):
    c = start(root, tmp_path / "ws")
    create_user(c.db, "ed@example.ro", PASSWORD, roles=("editor",))
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": "ed@example.ro", "password": PASSWORD},
    )
    c.csrf = c.cookies["nest_csrf"]
    yield c
    c.__exit__(None, None, None)


def category(site, ro_name, **english):
    r = site.post(
        "/admin/content/taxonomies/category/new",
        data={
            "csrf_token": site.csrf,
            "name": ro_name,
            "slug": "",
            "parent_id": "",
            "description": "",
        },
    )
    assert r.status_code == 303, r.text
    term = service.term_by(site.db, "category", name=ro_name, slug=ro_name)
    if english:
        translate(site, term.id, "content.term", english)
    return term


def translate(site, owner_id, subject, english):
    form = {
        "csrf_token": site.csrf,
        "lang": "en",
        "tr_en_present": "1",
        "tr_en_status": "published",
    }
    form |= {f"tr_en_{k}": v for k, v in english.items()}
    r = site.post(f"/admin/translations/{subject}/{owner_id}", data=form)
    assert r.status_code == 303, r.text


def post(site, ro_title, term, ro_body="<p>Text</p>", **english):
    """A post written in the editor, its English beside it."""
    data = {
        "csrf_token": site.csrf,
        "title": ro_title,
        "slug": "",
        "status": "published",
        "excerpt": "",
        "body": ro_body,
        "terms_category": str(term.id),
    }
    if english:
        data |= {"tr_en_present": "1", "tr_en_status": "published"}
        data |= {f"tr_en_{k}": v for k, v in english.items()}
    r = site.post("/admin/content/post/new", data=data)
    assert r.status_code == 303, r.text
    return service.entry(site.db, int(re.search(r"/post/(\d+)", r.headers["location"]).group(1)))


def alternates(page):
    return dict(
        re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="https?://[^/]+([^"]*)">', page)
    )


def test_a_translated_page_lives_at_its_english_address(site):
    stiai = category(site, "Știai că", name="Did you know", slug="did-you-know")
    church = post(
        site,
        "Biserica de lemn",
        stiai,
        "<p>Biserica satului.</p>",
        title="The wooden church",
        slug="the-wooden-church",
        body="<p>The village church.</p>",
    )
    assert church.path == "/stiai-ca/biserica-de-lemn/"
    en = site.get("/en/did-you-know/the-wooden-church/")
    assert en.status_code == 200, en.headers.get("location")
    assert (
        "The wooden church" in en.text
        and "The village church." in en.text
        and '<html lang="en"' in en.text
    )
    assert 'href="/en/category/did-you-know/"' in en.text  # its category, in English, under /en/
    ro = site.get("/stiai-ca/biserica-de-lemn/")
    assert "Biserica de lemn" in ro.text and "The wooden church" not in ro.text
    where = alternates(en.text)
    assert where == {
        "ro": "/stiai-ca/biserica-de-lemn/",
        "en": "/en/did-you-know/the-wooden-church/",
        "x-default": "/stiai-ca/biserica-de-lemn/",
    }


def test_each_address_sends_on_to_the_languages_own(site):
    stiai = category(site, "Știai că", name="Did you know", slug="did-you-know")
    post(site, "Biserica de lemn", stiai, title="The wooden church", slug="the-wooden-church")
    # the Romanian address asked in English, the English one asked in Romanian
    assert (
        site.get("/en/stiai-ca/biserica-de-lemn/").headers["location"]
        == "/en/did-you-know/the-wooden-church/"
    )
    assert (
        site.get("/did-you-know/the-wooden-church/").headers["location"]
        == "/stiai-ca/biserica-de-lemn/"
    )
    # so the language switch lands on the same page in the other language
    r = site.get("/_nest/language?language=en&next=/stiai-ca/biserica-de-lemn/")
    assert r.headers["location"] == "/en/stiai-ca/biserica-de-lemn/"
    assert (
        site.get(r.headers["location"]).headers["location"] == "/en/did-you-know/the-wooden-church/"
    )
    r = site.get("/_nest/language?language=ro&next=/did-you-know/the-wooden-church/")
    assert site.get(r.headers["location"]).headers["location"] == "/stiai-ca/biserica-de-lemn/"
    # categories too
    assert site.get("/en/category/stiai-ca/").headers["location"] == "/en/category/did-you-know/"
    page = site.get("/en/category/did-you-know/").text
    assert "Did you know" in page and "The wooden church" in page


def test_an_untranslated_page_shows_the_romanian_text_and_says_so(site):
    stiai = category(site, "Știai că")
    post(site, "Moara de apă", stiai, "<p>Moara veche.</p>")
    page = site.get("/en/stiai-ca/moara-de-apa/")
    assert page.status_code == 200 and "Moara de apă" in page.text and "Moara veche." in page.text
    where = alternates(page.text)
    assert "en" not in where and where["ro"] == "/stiai-ca/moara-de-apa/"  # no English to point at
    # its links keep the visitor in English; the listing shows it beside the translated ones
    assert 'href="/en/category/stiai-ca/"' in page.text
    assert "Moara de apă" in site.get("/en/").text


def test_an_english_slug_made_before_its_category_is_translated_follows_it(site):
    stiai = category(site, "Știai că")
    church = post(site, "Biserica", stiai, title="The church", slug="")  # slug from the title
    assert site.get("/en/stiai-ca/the-church/").status_code == 200
    translate(site, stiai.id, "content.term", {"name": "Did you know", "slug": "did-you-know"})
    assert site.get("/en/did-you-know/the-church/").status_code == 200
    with site.db.session() as s:
        assert s.get(EntryText, (church.id, "en")).path == "/did-you-know/the-church/"
    # a Romanian move moves the English address where it is made from the Romanian slug
    other = post(site, "Fântâna", stiai, title="The well", slug="the-well")
    r = site.post(
        f"/admin/content/taxonomies/category/{stiai.id}",
        data={
            "csrf_token": site.csrf,
            "name": "Știai că",
            "slug": "stiai",
            "parent_id": "",
            "description": "",
        },
    )
    assert r.status_code == 303
    assert site.get("/stiai/fantana/").status_code == 200
    assert site.get("/en/did-you-know/the-well/").status_code == 200  # its own English slug held
    assert other.id


def test_two_english_texts_never_share_an_address(site):
    stiai = category(site, "Știai că")
    a = post(site, "Hora", stiai, title="The dance", slug="the-dance")
    b = post(site, "Sârba", stiai, title="The dance", slug="the-dance")
    with site.db.session() as s:
        paths = {s.get(EntryText, (a.id, "en")).path, s.get(EntryText, (b.id, "en")).path}
    assert paths == {"/stiai-ca/the-dance/", "/stiai-ca/the-dance-2/"}


def test_a_draft_translation_is_not_shown(site):
    stiai = category(site, "Știai că")
    church = post(site, "Biserica", stiai, title="The church", slug="the-church")
    translate(
        site,
        church.id,
        "content.entry",
        {"title": "The church", "slug": "the-church", "status": "draft"},
    )
    form = {
        "csrf_token": site.csrf,
        "lang": "en",
        "tr_en_present": "1",
        "tr_en_status": "draft",
        "tr_en_title": "The church",
        "tr_en_slug": "the-church",
    }
    site.post(f"/admin/translations/content.entry/{church.id}", data=form)
    r = site.get("/en/stiai-ca/the-church/")
    assert r.status_code == 301 and r.headers["location"] == "/en/stiai-ca/biserica/"
    assert "Biserica" in site.get("/en/stiai-ca/biserica/").text  # the Romanian, standing in


def test_menus_search_feed_and_sitemap_in_english(site):
    stiai = category(site, "Știai că", name="Did you know", slug="did-you-know")
    church = post(
        site,
        "Biserica",
        stiai,
        "<p>Lemn de stejar.</p>",
        title="The church",
        slug="the-church",
        body="<p>Oak wood.</p>",
    )
    menu = service.ensure_menu(site.db, "main", "Meniu")
    service.add_menu_item(site.db, menu.id, entry_id=church.id)
    service.add_menu_item(site.db, menu.id, term_id=stiai.id, position=1)
    service.add_menu_item(site.db, menu.id, title="Contact", url="/contact/", position=2)
    en = service.menu_tree(site.db, "main", "en")
    assert [(n.title, n.url) for n in en] == [
        ("The church", "/did-you-know/the-church/"),
        ("Did you know", "/category/did-you-know/"),
        ("Contact", "/contact/"),
    ]
    assert [n.title for n in service.menu_tree(site.db, "main")] == [
        "Biserica",
        "Știai că",
        "Contact",
    ]
    # search: each language its own index
    assert "The church" in site.get("/en/search?q=oak").text
    assert "Biserica" not in site.get("/en/search?q=stejar").text
    assert "Biserica" in site.get("/search?q=stejar").text
    feed = site.get("/en/feed/").text
    assert (
        "<title>The church</title>" in feed
        and "/en/did-you-know/the-church/" in feed
        and "<language>en</language>" in feed
    )
    sitemap = site.get("/sitemap.xml").text
    assert "/en/did-you-know/the-church/" in sitemap and "/stiai-ca/biserica/" in sitemap
    # the editor's list says where each stands
    listing = site.get("/admin/content/post").text
    assert 'class="tr-state tr-published"' in listing


def test_the_edit_form_has_the_english_beside_and_says_when_it_is_outdated(site):
    stiai = category(site, "Știai că")
    church = post(site, "Biserica", stiai, title="The church", slug="the-church")
    form = site.get(f"/admin/content/post/{church.id}").text
    assert 'name="tr_en_title"' in form and 'value="The church"' in form
    site.post(
        f"/admin/content/post/{church.id}",
        data={
            "csrf_token": site.csrf,
            "title": "Biserica veche",
            "slug": "biserica",
            "status": "published",
            "excerpt": "",
            "body": "<p>Alt text.</p>",
            "terms_category": str(stiai.id),
        },
    )
    states = site.nest.lookup(
        "translations.states", {"subject": "content.entry", "ids": [church.id]}
    )
    assert states == {church.id: {"en": "outdated"}}


def test_records_older_than_the_text_tables_get_their_romanian_rows(root, tmp_path):
    ws = tmp_path / "ws"
    c = start(root, ws)
    e = service.save_entry(
        c.db, c.search, c.types, EntryData(type="page", title="Istoric", status="published")
    )
    with c.db.session() as s, s.begin():
        s.execute(delete(EntryText))  # as a database from before them
    c.__exit__(None, None, None)
    c = start(root, ws)
    with c.db.session() as s:
        rows = s.execute(
            select(EntryText.locale, EntryText.title, EntryText.path).where(
                EntryText.owner_id == e.id
            )
        ).all()
    assert rows == [("ro", "Istoric", "/istoric/")]
    c.__exit__(None, None, None)


def test_translations_imported_together_never_share_an_address(site):
    """A batch (an import) makes its addresses one after another: two English texts of the
    same title get -2, never the same address (and never an error from the database)."""
    from nest_translations import service as tr

    stiai = category(site, "Știai că")
    a = post(site, "Colo sus în vremea ceia", stiai)
    b = post(site, "Colo sus, în vremea-aceea", stiai)
    kinds = site.nest.module_state["translations"]["kinds"]
    data = {
        "format": "nest-translations/1",
        "source": "ro",
        "locale": "en",
        "items": [
            {
                "subject": "content.entry",
                "id": e.id,
                "text": {"title": "Up There in Those Days", "slug": "up-there-in-those-days"},
                "status": "published",
            }
            for e in (a, b)
        ],
    }
    written, refused, touched = tr.import_(site.db, kinds, data, ["ro", "en"], "ro")
    assert written == 2 and refused == []
    site.nest.module_state["translations"]["announce"](
        "content.entry", touched["content.entry"], ["en"]
    )
    with site.db.session() as s:
        paths = {s.get(EntryText, (a.id, "en")).path, s.get(EntryText, (b.id, "en")).path}
    assert paths == {"/stiai-ca/up-there-in-those-days/", "/stiai-ca/up-there-in-those-days-2/"}


def test_a_joomla_sites_leftover_tags_are_taken_out():
    from nest_content.html import strip_joomla_tags

    body = '<p>Text</p><p>{joomplu:962}{joomplu:963}</p><p>{gmapfp id="6" zmap="14"}</p><p>{edocs}judetul_alba.pdf,900,640{/edocs}</p><p>Mai mult{jcomments on}</p>'
    assert strip_joomla_tags(body) == "<p>Text</p><p>Mai mult</p>"
    assert strip_joomla_tags("<p>{not a tag of theirs}</p>") == "<p>{not a tag of theirs}</p>"


def test_the_english_body_is_written_in_the_editor_and_never_holds_a_script(site):
    """The translation page gives the body the same rich text editor as the original's; what
    it saves is cleaned as an original's body is, and a body that reached the database
    another way is cleaned again when shown."""
    stiai = category(site, "Știai că", name="Did you know", slug="did-you-know")
    church = post(site, "Biserica de lemn", stiai, "<p>Biserica satului.</p>")
    page = site.get(f"/admin/translations/content.entry/{church.id}?lang=en").text
    assert 'src="/assets/content/editor/editor.js' in page  # the editor is loaded
    body_field = re.search(r'<textarea id="tr_en_body"[^>]*>', page).group(0)
    assert "data-editor" in body_field and "data-labels=" in body_field
    assert "data-media-upload=" in body_field  # pictures, as in the original's editor

    translate(
        site,
        church.id,
        "content.entry",
        {
            "title": "The wooden church",
            "slug": "the-wooden-church",
            "body": '<p onmouseover="steal()">The church.</p><script>steal()</script>'
            '<a href="javascript:steal()">x</a><img src="x" onerror="steal()">',
        },
    )
    en = site.get("/en/did-you-know/the-wooden-church/").text
    assert "The church." in en
    assert "steal()" not in en and "<script>steal" not in en

    # a body put in the database some other way: cleaned when shown
    from nest_content.models import Entry

    with site.db.session() as s, s.begin():
        s.get(Entry, church.id).body = "<p>Biserica.</p><script>steal()</script>"
    ro = site.get("/stiai-ca/biserica-de-lemn/").text
    assert "Biserica." in ro and "steal()" not in ro
