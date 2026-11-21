"""The geo module: distances, a box for a database's first cut, ranking by distance, and
the near-me page every module with places contributes to (the only page allowed to ask
the browser where the reader is)."""

import textwrap

from fastapi.testclient import TestClient
from nest_geo import box, distance_km, near

from nest import create_app

APP = """
module: {name: harta, id: test.app.harta, type: application, version: 0.1.0}
application: {title: Hartă, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: geo, route: /aproape}
  - {name: maps, route: /harti}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def test_distances_and_boxes():
    assert round(distance_km(46.7712, 23.6236, 44.4268, 26.1025)) == 324  # Cluj – București
    assert distance_km(45, 25, 45, 25) == 0
    s, w, n, e = box(46.77, 23.62, 10)
    assert s < 46.77 < n and w < 23.62 < e and round(n - s, 2) == 0.18
    places = [("a", 46.77, 23.62), ("b", 46.80, 23.70), ("c", 44.43, 26.10), ("d", None, None)]
    ranked = near(places, 46.77, 23.62, lambda p: (p[1], p[2]), km=50)
    assert [p[0] for p, _km in ranked] == ["a", "b"]


def test_the_near_me_page_gathers_every_module(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    from nest_maps import service as maps
    from nest_maps.service import MapData, MarkerData

    db = app.state.nest.bindings.get("nest.db")
    maps.save_map(
        db,
        MapData(
            title="Satul",
            lat=46.77,
            lng=23.62,
            zoom=12,
            markers=[MarkerData(lat=46.771, lng=23.621, title="Biserica", description="", link="")],
        ),
    )
    with TestClient(app) as c:
        page = c.get("/aproape/")
        assert page.status_code == 200 and "geolocation=(self)" in page.headers["permissions-policy"]
        assert "geolocation=()" in c.get("/harti/").headers["permissions-policy"]  # only this page
        near_page = c.get("/aproape/places?lat=46.77&lon=23.62").text
        assert "Biserica" in near_page and "0.1 km" in near_page
        assert "Nimic în apropiere" in c.get("/aproape/places?lat=10&lon=10").text
        assert c.get("/aproape/places?lat=999&lon=0").status_code == 400
