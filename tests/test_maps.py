"""The maps module: maps and markers, the page of places, shortcodes, GeoJSON, WP Google Maps."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_content import service as content
from nest_content.service import EntryData
from nest_maps import service
from nest_maps.service import MapData, MapsError
from nest_maps.wordpress import import_dump

from nest import create_app

PASSWORD = "correct horse battery"

APP = """
module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}
application: {title: Satul, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: content, route: /}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
  - {name: media, route: /media}
  - {name: maps, route: /harta}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
content_types:
  place:
    title: Obiective
    path: "/obiective/{slug}/"
    fields:
      lat: {type: decimal, label: Latitudine}
      lng: {type: decimal, label: Longitudine}
"""

WPGMZA = r"""
CREATE TABLE `wp_wpgmza_maps` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `map_title` varchar(55) NOT NULL,
  `map_start_lat` varchar(700) NOT NULL,
  `map_start_lng` varchar(700) NOT NULL,
  `map_start_zoom` int(10) NOT NULL,
  `active` int(1) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `wp_wpgmza_maps` VALUES (1,'Morlaca','46.858614','22.919598',15,0),(2,'Ștearsă','46','22',10,1);
CREATE TABLE `wp_wpgmza` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `map_id` int(11) NOT NULL,
  `address` varchar(700) NOT NULL,
  `description` mediumtext NOT NULL,
  `link` varchar(700) NOT NULL,
  `lat` varchar(100) NOT NULL,
  `lng` varchar(100) NOT NULL,
  `title` varchar(700) NOT NULL,
  `approved` tinyint(1) DEFAULT '1',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `wp_wpgmza` VALUES (2,1,'Morlaca, Județul Cluj, România','','','46.85749879999999','22.91792429999998','',1),(3,1,'x','','javascript:alert(1)','46.86','22.92','Fântâna',1);
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
        yield c


def sign_in(c):
    create_user(c.db, "ed@example.ro", PASSWORD, roles=("editor",))
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": "ed@example.ro", "password": PASSWORD},
    )


def test_markers_are_lines_of_text_and_bad_ones_are_named():
    marks = service.parse_markers(
        "# the village\n46.8575, 22.9179, Biserica de lemn, /obiective/biserica/\n\n46,86, 22.92\n"
    )
    assert [(m.lat, m.lng, m.title, m.link) for m in marks] == [
        (46.8575, 22.9179, "Biserica de lemn", "/obiective/biserica/"),
        (46.0, 86.0, "22.92", ""),  # a comma is a separator, never a decimal point here
    ]
    with pytest.raises(MapsError) as e:
        service.parse_markers("46.85, 22.91, Ok\n95, 22, Prea la nord")
    assert e.value.params["n"] == 2
    with pytest.raises(MapsError):
        service.parse_markers("46.85, 22.91, Rău, javascript:alert(1)")
    with pytest.raises(MapsError):
        service.parse_markers("46.85, 22.91, Rău, //evil.example.com/")


def test_an_editor_makes_a_map_and_the_page_shows_it_with_every_place(site):
    sign_in(site)
    csrf = site.cookies["nest_csrf"]
    r = site.post(
        "/admin/maps/new",
        data={
            "csrf_token": csrf,
            "title": "Satul Morlaca",
            "lat": "46.8586",
            "lng": "22.9196",
            "zoom": "15",
            "markers": "46.8575, 22.9179, Centru <b>vechi</b>, /despre/",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    bad = site.post(
        "/admin/maps/new",
        data={"csrf_token": csrf, "title": "X", "lat": "200", "lng": "1"},
    )
    assert bad.status_code == 400 and "nu este o coordonată" in bad.text
    content.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="place",
            title="Biserica de lemn",
            status="published",
            body="<p>Din 1791.</p>",
            fields={"lat": "46.8571", "lng": "22.9183"},
        ),
    )
    page = site.get("/harta/")
    assert page.status_code == 200
    assert (
        'class="map"' in page.text
        and 'data-map="/harta/satul-morlaca.geojson?places=1"' in page.text
    )
    assert "/assets/maps/maps.js" in page.text
    assert '<a href="/obiective/biserica-de-lemn/">Biserica de lemn</a>' in page.text
    assert "https://tile.openstreetmap.org" in page.headers["content-security-policy"]
    data = site.get("/harta/satul-morlaca.geojson?places=1").json()
    titles = [f["properties"]["title"] for f in data["features"]]
    assert titles == ["Centru <b>vechi</b>", "Biserica de lemn"]  # data, drawn as text
    assert data["features"][1]["geometry"]["coordinates"] == [22.9183, 46.8571]
    assert len(site.get("/harta/satul-morlaca.geojson").json()["features"]) == 1
    assert site.get("/harta/satul-morlaca/").status_code == 200
    assert site.get("/harta/nu-exista/").status_code == 404


def test_shortcodes_and_wordpress_maps(site, tmp_path):
    dump = tmp_path / "wp.sql"
    dump.write_text(WPGMZA, encoding="utf-8")
    report = import_dump(site.db, dump)
    assert (report.maps, report.markers) == (1, 2)
    assert any("deleted" in s for s in report.skipped)
    m = service.map_by(site.db, legacy_id=1)
    assert (m.slug, m.zoom, round(m.lat, 4)) == ("morlaca", 15, 46.8586)
    marks = service.markers(site.db, m.id)
    assert marks[0].title == "Morlaca, Județul Cluj, România" and marks[1].link == ""
    assert import_dump(site.db, dump).maps == 1  # again: updated, not doubled
    assert len(service.maps(site.db)) == 1
    content.save_entry(
        site.db,
        site.search,
        site.types,
        EntryData(
            type="page",
            title="Așezarea",
            status="published",
            body='<p>[wpgmza id="1"]</p><p>[map lat="46.85" lng="22.91" zoom="12" title="Aici"]</p>',
        ),
    )
    page = site.get("/asezarea/").text
    assert 'data-map="/harta/morlaca.geojson"' in page
    assert 'data-map="/harta/point.geojson?lat=46.85&amp;lng=22.91&amp;title=Aici"' in page
    assert "[wpgmza" not in page
    point = site.get("/harta/point.geojson?lat=46.85&lng=22.91&title=Aici").json()
    assert point["features"][0]["properties"]["title"] == "Aici"


def test_a_map_needs_a_title_and_its_own_address(site):
    service.save_map(site.db, MapData(title="Sat", lat=46, lng=22))
    with pytest.raises(MapsError, match="address"):
        service.save_map(site.db, MapData(title="Sat", lat=46, lng=22))
    with pytest.raises(MapsError, match="title"):
        service.save_map(site.db, MapData(title=" ", lat=46, lng=22))


# --- where the tiles come from: the settings, per application ----------------------


def test_providers_make_the_tile_address_with_the_key():
    from nest_maps.providers import TilesError, problems, tiles

    base = {
        "provider": "osm",
        "api_key": "",
        "style": "",
        "attribution": "",
        "max_zoom": 0,
        "tiles": "",
    }
    osm = tiles(base)
    assert osm.url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png" and osm.max_zoom == 19
    mt = tiles({**base, "provider": "maptiler", "api_key": "AbC123xyz"})
    assert mt.url == "https://api.maptiler.com/maps/outdoor-v2/256/{z}/{x}/{y}.png?key=AbC123xyz"
    assert mt.origin == "https://api.maptiler.com" and "MapTiler" in mt.attribution
    tf = tiles({**base, "provider": "thunderforest", "api_key": "k3y-ok", "style": "landscape"})
    assert tf.url.startswith("https://tile.thunderforest.com/landscape/") and tf.url.endswith(
        "apikey=k3y-ok"
    )
    own = tiles(
        {
            **base,
            "provider": "custom",
            "tiles": "https://dale.morlaca.ro/{z}/{x}/{y}.png?k={key}",
            "api_key": "abcd",
            "attribution": "<b>Noi</b>",
        }
    )
    assert own.url.endswith("?k=abcd") and own.origin == "https://dale.morlaca.ro"
    assert own.attribution == "&lt;b&gt;Noi&lt;/b&gt;"  # a typed credit is text
    assert problems({**base, "provider": "maptiler"}) == [
        ("{provider} needs this site's API key.", {"provider": "maptiler"})
    ]
    for bad in (
        {**base, "provider": "custom", "tiles": "http://x.ro/{z}/{x}/{y}.png"},
        {**base, "provider": "custom", "tiles": "https://x.ro/tiles.png"},
        {**base, "provider": "stadia", "api_key": 'bad key"><script>'},
        {**base, "style": "../../etc"},
    ):
        with pytest.raises(TilesError):
            tiles(bad)


def sign_in_admin(c):
    create_user(c.db, "admin@example.ro", PASSWORD, roles=("admin",))
    c.get("/healthz")
    c.post(
        "/cont/login",
        data={
            "csrf_token": c.cookies["nest_csrf"],
            "email": "admin@example.ro",
            "password": PASSWORD,
        },
    )


def test_an_administrator_sets_the_provider_and_key_for_this_application(site):
    sign_in_admin(site)
    service.save_map(site.db, MapData(title="Morlaca", lat=46.8586, lng=22.9196, zoom=15))
    first = site.get("/admin/settings", follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"].startswith("/admin/settings/")
    page = site.get("/admin/settings/maps")
    assert page.status_code == 200 and 'id="maps"' in page.text and "Furnizorul hărții" in page.text
    assert 'href="/admin/settings/content"' in page.text  # the other sections: a tab away
    assert 'id="content"' not in page.text
    csrf = site.cookies["nest_csrf"]
    form = {
        "csrf_token": csrf,
        "maps.provider": "maptiler",
        "maps.api_key": "",
        "maps.style": "",
        "maps.tiles": "",
        "maps.attribution": "",
        "maps.max_zoom": "0",
        "maps.main": "",
    }
    refused = site.post("/admin/settings/maps", data=form)
    assert refused.status_code == 400 and "cere cheia API" in refused.text
    assert site.nest.settings.get("maps.provider") == "osm"  # nothing saved
    ok = site.post(
        "/admin/settings/maps", data={**form, "maps.api_key": "AbC123xyz"}, follow_redirects=False
    )
    assert ok.status_code == 303 and ok.headers["location"] == "/admin/settings/maps"
    assert site.nest.settings.get("maps.api_key") == "AbC123xyz"
    shown = site.get("/harta/")
    assert (
        'data-tiles="https://api.maptiler.com/maps/outdoor-v2/256/{z}/{x}/{y}.png?key=AbC123xyz"'
        in shown.text
    )
    assert "https://api.maptiler.com" in shown.headers["content-security-policy"]
    # a custom host is let in, and the one before it is let go
    custom = {
        **form,
        "maps.provider": "custom",
        "maps.tiles": "https://dale.morlaca.ro/{z}/{x}/{y}.png",
    }
    site.post("/admin/settings/maps", data=custom)
    csp = site.get("/harta/").headers["content-security-policy"]
    assert "https://dale.morlaca.ro" in csp
    back = site.post(
        "/admin/settings/maps",
        data={**form, "csrf_token": csrf, "reset:maps.provider": "1", "maps.api_key": ""},
    )
    assert back.status_code in (200, 303) and site.nest.settings.get("maps.provider") == "osm"
    assert "dale.morlaca.ro" not in site.get("/harta/").headers["content-security-policy"]


def test_only_administrators_change_settings(site):
    sign_in(site)  # an editor
    assert site.get("/admin/settings").status_code == 403
    assert (
        site.post(
            "/admin/settings/maps", data={"csrf_token": site.cookies["nest_csrf"]}
        ).status_code
        == 403
    )


def test_a_value_from_the_environment_is_shown_not_changed(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(
        root,
        environ={
            "NEST_APP_WORKSPACE": str(tmp_path / "ws"),
            "NEST_SAT__MAPS__PROVIDER": "opentopomap",
        },
    )
    with TestClient(app) as c:
        c.db = app.state.nest.bindings.get("nest.db")
        sign_in_admin(c)
        page = c.get("/admin/settings/maps").text
        section = page.split('id="maps"', 1)[1]
        assert "Setată în mediul serverului" in section
        assert (
            'name="maps.provider" disabled' in section
            or 'id="s-maps-provider" name="maps.provider" disabled' in section
        )
