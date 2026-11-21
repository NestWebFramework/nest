"""Reaching a module without code: blocks in a theme's regions (the home page among
them), a menu link from a module's Place it, and the registry showing only what fits the
application's type. Identity cards say category and fits, checked."""

import textwrap

import pytest
from nest_auth.sessions import create_user
from nest_content import service
from test_content_languages import PASSWORD, start

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {type: site, title: Satul, port: 8000, theme: base, languages: [en]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: forum, route: /forum}
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
    c = start(root, tmp_path / "ws")
    create_user(c.db, "root@example.org", PASSWORD, roles=("admin",))
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={
            "csrf_token": c.cookies["nest_csrf"],
            "email": "root@example.org",
            "password": PASSWORD,
        },
    )
    c.csrf = c.cookies["nest_csrf"]
    yield c
    c.__exit__(None, None, None)


def post(c, to, **data):
    return c.post(to, data={"csrf_token": c.csrf, **data})


def home(site):
    service.save_entry(
        site.db, site.search, site.types,
        service.EntryData(type="page", title="Acasă", slug="acasa", status="published", body="<p>Bine ați venit.</p>"),
    )  # fmt: skip
    return "/acasa/"


def test_blocks_go_in_the_themes_regions_without_code(site):
    from nest_forum import service as forum

    page = site.get("/admin/themes/regions").text
    assert all(
        r in page
        for r in ("<code>home</code>", "<code>after_content</code>", "<code>footer</code>")
    )
    assert "Latest forum topics" in page and "Newest articles" in page  # offered by forum, content

    b = forum.ensure_board(site.db, "General")
    member = site  # the administrator writes a topic
    member.post(
        f"/forum/{b.slug}/new",
        data={"csrf_token": site.csrf, "title": "Hora satului", "body": "Când?"},
    )
    url = home(site)
    assert "Latest in the forum" not in site.get(url).text

    r = post(site, "/admin/themes/regions/add", region="after_content", block="forum.latest")
    assert r.status_code == 303
    shown = site.get(url).text
    assert "Latest in the forum" in shown and "Hora satului" in shown
    assert 'data-region="after_content"' in shown

    service.save_entry(
        site.db, site.search, site.types,
        service.EntryData(type="post", title="Sărbătoarea satului", status="published", body="<p>Duminică.</p>"),
    )  # fmt: skip
    post(site, "/admin/themes/regions/add", region="footer", block="content.latest")
    post(site, "/admin/themes/regions/footer/0", action="save", **{"setting:count": "1"})
    footer = site.get(url).text.split('class="container footer-region"')[1]
    assert "Newest articles" in footer and "Sărbătoarea satului" in footer
    from nest import regions

    assert regions.load(site.nest.workspace)["footer"][0].settings == {"count": "1"}

    post(site, "/admin/themes/regions/after_content/0", action="remove")
    assert "Latest in the forum" not in site.get(url).text
    assert "Latest in the forum" not in site.get("/admin/").text  # never in the admin panel
    refused = post(site, "/admin/themes/regions/add", region="nowhere", block="forum.latest")
    assert refused.status_code == 400


def test_place_it_links_a_module_from_a_menu(site):
    page = site.get("/admin/modules/forum").text
    assert "Place it on the site" in page and "The site has no menu yet" in page
    assert "Latest forum topics" in page  # its block, with the regions to choose
    post(site, "/admin/content/menus", title="Main menu", slug="main")
    page = site.get("/admin/modules/forum").text
    assert 'name="menu"' in page and "/forum/" in page
    r = post(site, "/admin/modules/forum/place-menu", menu="main", title="Discuții")
    assert r.status_code == 200 and "A link to it is in the menu main." in r.text
    url = home(site)
    menu = site.get(url).text.split('class="menu"')[1].split("</ul>")[0]
    assert 'href="/forum/"' in menu and "Discuții" in menu


def test_the_registry_shows_what_fits_this_application(site, monkeypatch):
    import nest.packages
    from nest.packages import Offer

    def offer(name, category, fits, kind="module", part_of=None):
        return Offer(
            name=name, dist=f"nest-{name}", version="1.0.0", type=kind, title=name.title(), description="",
            source="remote", index="https://r.example/simple/", nest=">=0.2,<1", category=category,
            fits=fits, part_of=part_of,
        )  # fmt: skip

    found = {
        "polls": offer("polls", "community", ["site", "game"]),
        "saga": offer("saga", "game", ["game"]),
        "farm": offer("farm", "game", ["game"], kind="subsystem", part_of="saga"),
        "keeper": offer("keeper", "platform", ["keeper"]),
        "redis": offer("redis", "infrastructure", ["any"], kind="provider"),
        "oldie": offer("oldie", None, []),  # says nothing: fits any
    }
    monkeypatch.setattr(nest.packages, "remote_offers", lambda environ=None: found)
    page = site.get("/admin/modules?tab=registry").text
    assert "<code>polls</code>" in page and "<code>oldie</code>" in page
    assert all(f"<code>{n}</code>" not in page for n in ("saga", "farm", "keeper", "redis"))
    assert "4 others are for other kinds of applications" in page
    everything = site.get("/admin/modules?tab=registry&everything=1").text
    saga = everything.split("<code>saga</code>")[1].split("</tr>")[0]
    assert "not for this application" in saga and "/admin/modules/add" not in saga
    community = site.get("/admin/modules?tab=registry&category=community").text
    assert "<code>polls</code>" in community and "<code>oldie</code>" not in community


def test_identity_cards_say_category_and_fits(tmp_path):
    from nest.manifest import ManifestError, load_manifest

    pkg = tmp_path / "m"
    pkg.mkdir()
    card = "module: {name: m, id: test.m, type: module, version: 0.1.0, category: %s, fits: %s}\n"
    (pkg / "module.yml").write_text(card % ("community", "[site, game]"))
    m = load_manifest(pkg)
    assert (
        m.module.fits_type("game")
        and m.module.fits_type("site")
        and not m.module.fits_type("keeper")
    )
    (pkg / "module.yml").write_text(card % ("gossip", "[site]"))
    with pytest.raises(ManifestError, match="category 'gossip'"):
        load_manifest(pkg)
    (pkg / "module.yml").write_text(card % ("community", "[casino]"))
    with pytest.raises(ManifestError, match="not an application type"):
        load_manifest(pkg)
