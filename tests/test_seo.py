"""The seo module: what editors say of each page, what pages tell search engines and shared
links, the sitemap with photos, robots.txt, and the modules that take part."""

import json
import re
import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_content import service as content
from nest_content.service import EntryData
from nest_gallery import service as gallery

from nest import create_app

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Morlaca, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: gallery, route: /galerii}
  - {name: maps, route: /harta}
  - name: seo
    config:
      site_url: https://morlaca.ro
      description: Satul de la poalele Vlădesei.
      keywords: Morlaca, Poieni, Cluj
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
    with TestClient(app) as c:
        n = app.state.nest
        c.nest = n
        c.db, c.search = n.bindings.get("nest.db"), n.bindings.get("nest.search")
        c.types = n.module_state["content"]["types"]
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
        yield c


def ld(html):
    return [
        json.loads(m)
        for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html)
    ]


def post(site, page_title, **seo):
    data = {
        "csrf_token": site.cookies["nest_csrf"],
        "title": page_title,
        "status": "published",
        "body": "<p>Biserica a fost ridicată în 1838.</p>",
        "seo_present": "1",
    }
    data.update({f"seo_{k}": v for k, v in seo.items()})
    return site.post("/admin/content/post/new", data=data, follow_redirects=False)


def test_an_editor_describes_an_article_for_search_engines(site):
    page = site.get("/admin/content/post/new").text
    assert 'name="seo_description"' in page and "Motoare de căutare și distribuire" in page
    r = post(
        site,
        "Biserica de lemn",
        title="Biserica din Morlaca (1838)",
        description="Istoria bisericii ortodoxe din Morlaca.",
        keywords="biserică, Morlaca, biserică",
    )
    assert r.status_code == 303
    e = (
        content.entry_by_path(site.db, "/uncategorized/biserica-de-lemn/")
        or content.published_entries(site.db)[0]
    )
    html = site.get(e.path).text
    assert "<title>Biserica din Morlaca (1838) · Morlaca</title>" in html
    assert '<meta name="description" content="Istoria bisericii ortodoxe din Morlaca.">' in html
    assert '<meta name="keywords" content="biserică, Morlaca, Poieni, Cluj">' in html  # each once
    assert f'<link rel="canonical" href="https://morlaca.ro{e.path}">' in html
    assert "max-image-preview:large" in html
    article = [d for d in ld(html) if d["@type"] == "Article"][0]
    assert (
        article["headline"] == "Biserica din Morlaca (1838)"
        and article["publisher"]["name"] == "Morlaca"
    )
    form = site.get(f"/admin/content/post/{e.id}").text
    assert 'value="Biserica din Morlaca (1838)"' in form  # it comes back in the editor


def test_a_bad_canonical_keeps_the_whole_page_unsaved(site):
    r = post(site, "Portul", canonical="javascript:alert(1)")
    assert r.status_code == 400 and "Adresa canonică" in r.text
    assert content.published_entries(site.db) == []


def test_a_hidden_page_says_noindex_and_leaves_the_sitemap(site):
    post(site, "Ciornă publică", noindex="1")
    post(site, "Istoria")
    hidden, shown = sorted(content.published_entries(site.db), key=lambda e: e.title)
    html = site.get(hidden.path).text
    assert (
        '<meta name="robots" content="noindex, follow">' in html
        and "application/ld+json" not in html
    )
    sitemap = site.get("/sitemap.xml").text
    assert hidden.path not in sitemap and f"https://morlaca.ro{shown.path}" in sitemap


def test_galleries_are_described_and_their_photos_go_to_the_sitemap(site):
    c = gallery.ensure(site.db, "De prin sat", description="Fotografii din 2012.")
    gallery.set_photos(
        site.db, c.id, [{"key": "uploads/a.jpg"}, {"key": "uploads/b.jpg", "caption": "Ulița mare"}]
    )
    photos = gallery.photos(site.db, c.id)
    page = site.get(f"/admin/gallery/{c.id}")
    assert (
        page.status_code == 200
        and f'name="alt_{photos[0].id}"' in page.text
        and 'name="seo_title"' in page.text
    )
    r = site.post(
        f"/admin/gallery/{c.id}",
        data={
            "csrf_token": site.cookies["nest_csrf"],
            "title": "De prin sat",
            "description": "Fotografii din sat, 2012.",
            "published": "1",
            "cover": "",
            f"alt_{photos[0].id}": "Biserica văzută din deal",
            f"caption_{photos[0].id}": "Biserica, vara",
            f"alt_{photos[1].id}": "",
            f"caption_{photos[1].id}": "Ulița mare",
            "seo_present": "1",
            "seo_description": "Imagini vechi și noi din Morlaca.",
            "seo_keywords": "fotografii",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    html = site.get("/galerii/de-prin-sat/").text
    assert (
        'alt="Biserica văzută din deal"' in html and 'alt="Ulița mare"' in html
    )  # the caption, when no description
    assert '<meta name="description" content="Imagini vechi și noi din Morlaca.">' in html
    album = [d for d in ld(html) if d["@type"] == "ImageGallery"][0]
    assert album["image"][0] == {
        "@type": "ImageObject",
        "contentUrl": "https://morlaca.ro/media/uploads/a.jpg",
        "name": "Biserica văzută din deal",
        "caption": "Biserica, vara",
    }
    sitemap = site.get("/sitemap.xml").text
    assert "<loc>https://morlaca.ro/galerii/de-prin-sat/</loc>" in sitemap
    assert (
        "<image:loc>https://morlaca.ro/media/uploads/a.jpg</image:loc><image:title>Biserica văzută din deal</image:title>"
        in sitemap
    )
    assert 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' in sitemap
    assert "<loc>https://morlaca.ro/harta/</loc>" in sitemap  # the maps module's pages too


def test_the_site_defaults_robots_and_the_home_page(site):
    site.nest.settings.set("seo.google_verification", "abc123")
    site.nest.settings.set("seo.robots_closed", "/ciorne, nu-e-cale")
    home = site.get("/").text
    assert '<meta name="google-site-verification" content="abc123">' in home
    assert '<meta name="description" content="Satul de la poalele Vlădesei.">' in home
    assert [d for d in ld(home) if d["@type"] == "WebSite"]
    site.nest.production = True
    robots = site.get("/robots.txt").text
    assert (
        "Disallow: /admin/" in robots
        and "Disallow: /ciorne/" in robots
        and "nu-e-cale" not in robots
    )
    assert "Sitemap: https://morlaca.ro/sitemap.xml" in robots


def test_structured_data_cannot_close_its_script(site):
    post(site, "Titlu", title="</script><script>alert(1)</script>")
    e = content.published_entries(site.db)[0]
    html = site.get(e.path).text
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script\\u003e" in html


def test_the_overview_shows_what_is_missing(site):
    post(site, "Fără descriere")
    post(site, "Cu descriere", description="Ceva.")
    page = site.get("/admin/seo/?group=Posts&missing=1").text
    assert "Fără descriere" in page and "Cu descriere" not in page.split("<tbody>")[1]
    assert 'aria-current="page">Articole' in page  # a tab per kind of page
    assert 'href="?group=Galleries"' in page and 'href="?group=Maps"' in page


def test_a_proposal_is_made_from_the_pages_own_text():
    from nest_seo.suggest import propose

    p = propose(
        "Cetatea de la Bologa",
        "<p>No, servus!</p><p>Cetatea medievală <span>B</span>ologa este amplasată în localitatea cu același nume, "
        "în apropierea locului de vărsare a pârâului Secuieu în Crișul Repede. Cetatea Bologa a aparținut "
        "regelui Carol Robert. Ruinele cetății se văd de pe drumul spre Huedin.</p>[map]",
    )
    assert p.description.startswith("Cetatea medievală Bologa este amplasată")  # not the greeting
    assert len(p.description) <= 156 and "[map]" not in p.description
    words = p.keywords.split(", ")
    assert "Bologa" in p.keywords and "Crișul Repede" in words and "Carol Robert" in words
    assert not {"este", "același", "în"} & {w.lower() for w in words}


def test_an_editor_asks_for_a_proposal_and_for_a_tab_of_them(site):
    r = site.post(
        "/admin/seo/suggest",
        data={
            "title": "Portul popular",
            "text": ["<p>Costumul popular din Morlaca are cămăși de pânză albă.</p>"],
        },
        headers={"x-csrf-token": site.cookies["nest_csrf"]},
    )
    assert r.status_code == 200 and "Morlaca" in r.json()["keywords"]
    assert r.json()["description"].startswith("Costumul popular din Morlaca")
    page = site.get("/admin/content/post/new").text
    assert "Propune din text" in page and 'data-url="/admin/seo/suggest"' in page
    post(site, "Istoria satului")  # its text: "Biserica a fost ridicată în 1838."
    post(site, "Descris", description="Deja descris.")
    tab = site.get("/admin/seo/?group=Posts").text
    assert 'href="/admin/seo/batch?group=Posts"' in tab
    site.post(
        "/admin/seo/propose", data={"csrf_token": site.cookies["nest_csrf"], "group": "Posts"}
    )
    entries = {e.title: e for e in content.published_entries(site.db)}
    html = site.get(entries["Istoria satului"].path).text
    assert '<meta name="description" content="Biserica a fost ridicată în 1838.">' in html
    assert (
        '<meta name="description" content="Deja descris.">'
        in site.get(entries["Descris"].path).text
    )


def test_a_proposed_title_says_what_the_page_is_about_and_short_pages_still_get_keywords():
    from nest_seo.suggest import propose

    p = propose(
        "Cetatea de la Bologa",
        "<p>Cetatea medievală Bologa e lângă Crișul Repede.</p>",
        context=["Obiective turistice"],
        site="Morlaca",
    )
    assert p.title == "Cetatea de la Bologa – Obiective turistice"
    p = propose(
        "Istoria satului",
        "<p>Satul Morlaca e vechi. Morlaca e la poalele Vlădesei.</p>",
        context=["Uncategorized"],
        site="Morlaca",
    )
    assert (
        p.title == "Istoria satului – Vlădesei" and "Uncategorized" not in p.title
    )  # never the site's name
    p = propose("Posibilităţi de cazare în zonă", "<p>Pensiuni.</p>", context=["Turism"])
    assert "Turism" in p.keywords and len(p.keywords.split(", ")) >= 3


def test_file_names_and_camera_records_are_not_proposed():
    from nest_seo.suggest import propose

    p = propose(
        "De prin sat",
        "Fotografii din sat, 2012.",
        "morlaca035 20121226 1435168974",
        "Aperture: 7.1\nCamera: NIKON D40\nIso: 200\nOrientation: 1",
        "Ulița mare, iarna",
    )
    assert "NIKON" not in p.title + p.description + p.keywords and "20121226" not in p.description
    assert p.description.startswith("Fotografii din sat, 2012.")


def test_a_batch_is_previewed_applied_page_by_page_and_undone(site):
    csrf = site.cookies["nest_csrf"]
    post(site, "Istoria satului")
    post(site, "Portul popular", title="Portul nostru")  # an editor's title, kept
    post(site, "Cântece")
    entries = {e.title: e for e in content.published_entries(site.db)}
    form = site.get("/admin/seo/batch?group=Posts").text
    assert 'value="Posts" checked' in form and "Completează doar ce e gol" in form
    preview = site.post(
        "/admin/seo/batch/preview",
        data={
            "csrf_token": csrf,
            "group": ["Posts"],
            "field": ["title", "description", "keywords"],
            "mode": "empty",
        },
    ).text
    port = f"content.entry:{entries['Portul popular'].id}"
    assert (
        f'name="new:description:{port}"' in preview and f'name="new:title:{port}"' not in preview
    )  # written: kept
    assert "Salvează paginile bifate" in preview
    import re

    fields = dict(re.findall(r'name="(new:[^"]+)" value="([^"]*)"', preview))
    keep_out = f"content.entry:{entries['Cântece'].id}"
    picked = [s for s in {k.split(":", 2)[2] for k in fields} if s != keep_out]
    site.post("/admin/seo/batch/apply", data={"csrf_token": csrf, "subject": picked, **fields})
    istoria = site.get(entries["Istoria satului"].path).text
    assert '<meta name="description" content="Biserica a fost ridicată în 1838.">' in istoria
    assert "<title>Istoria satului" in istoria and '<meta name="keywords"' in istoria
    assert "<title>Portul nostru · Morlaca</title>" in site.get(entries["Portul popular"].path).text
    from nest_seo import service as seo

    assert seo.get(site.db, keep_out) is None  # left out: nothing saved for it
    every = site.post(
        "/admin/seo/batch/preview",
        data={"csrf_token": csrf, "group": ["Posts"], "field": ["title"], "mode": "all"},
    ).text
    assert (
        f'name="new:title:{port}"' in every and "<del>Portul nostru</del>" in every
    )  # offered, to choose
    assert "Anulează ultima operație" in site.get("/admin/seo/batch").text
    site.post("/admin/seo/batch/undo", data={"csrf_token": csrf})
    assert (
        seo.get(site.db, f"content.entry:{entries['Istoria satului'].id}") is None
    )  # back as it was
    assert "<title>Portul nostru · Morlaca</title>" in site.get(entries["Portul popular"].path).text


def test_a_category_is_a_collection_with_its_way_home(site):
    from nest_content.service import TermData

    term, _moves = content.save_term(
        site.db, site.search, site.types, "category", TermData(name="Știai că?")
    )
    content.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="post",
            title="Morlaca și Menumorut",
            status="published",
            body="<p>Text.</p>",
            terms={"category": [term.id]},
        ),
    )
    page = site.get(term.path).text
    kinds = [d["@type"] for d in ld(page)]
    assert "CollectionPage" in kinds and "BreadcrumbList" in kinds
    trail = [d for d in ld(page) if d["@type"] == "BreadcrumbList"][0]["itemListElement"]
    assert [(i["name"], i["item"]) for i in trail] == [
        ("Morlaca", "https://morlaca.ro/"),
        ("Știai că?", f"https://morlaca.ro{term.path}"),
    ]
    assert '<meta property="og:locale" content="ro_RO">' in page
    article = content.published_entries(site.db)[0]
    steps = [d for d in ld(site.get(article.path).text) if d["@type"] == "BreadcrumbList"][0][
        "itemListElement"
    ]
    assert [i["name"] for i in steps] == ["Morlaca", "Știai că?", "Morlaca și Menumorut"]


def test_categories_take_part_in_the_overview_and_the_batch(site):
    from nest_content.service import TermData

    term, _ = content.save_term(
        site.db, site.search, site.types, "category", TermData(name="Tradiții")
    )
    content.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="post",
            title="Nedeia",
            status="published",
            body="<p>Hora satului.</p>",
            terms={"category": [term.id]},
        ),
    )
    tab = site.get("/admin/seo/?group=Categories").text
    assert "Tradiții" in tab and f"/admin/content/taxonomies/category/{term.id}" in tab
    preview = site.post(
        "/admin/seo/batch/preview",
        data={
            "csrf_token": site.cookies["nest_csrf"],
            "group": ["Categories"],
            "field": ["description"],
            "mode": "empty",
        },
    ).text
    assert f'name="new:description:content.term:{term.id}"' in preview
