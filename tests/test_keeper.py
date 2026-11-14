"""The keeper: Nest's applications, their plans and problems, whether they run, the packages."""

import textwrap
from pathlib import Path

from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_keeper import applications

from nest import create_app

REPO = Path(__file__).resolve().parents[1]

APP = """
module: {name: keeper, id: test.app.keeper, type: application, version: 0.1.0}
application: {title: Keeper, port: 8000, theme: base}
modules:
  - name: keeper
    route: /
    config: {apps: "APPS"}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def test_every_application_is_found_and_planned():
    apps = {a.name: a for a in applications([REPO / "applications"])}
    assert {"voievodate", "gari", "morlaca", "transilpedia", "regionalisme", "keeper"} <= set(apps)
    voievodate = apps["voievodate"]
    assert voievodate.port == 8500 and not voievodate.problems
    names = [u["name"] for u in voievodate.units]
    assert names.index("game") < names.index("npc") and {"admin", "economy"} <= set(names)
    assert voievodate.bindings == {"nest.db": ["db-sqlite"]}


def test_a_broken_application_shows_its_problems(tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "module.yml").write_text(
        "module: {name: broken, id: x.broken, type: application, version: 0.1.0}\n"
        "application: {port: 9999}\nmodules:\n  - {name: nowhere}\n",
        encoding="utf-8",
    )
    (broken,) = [a for a in applications([tmp_path]) if a.name == "broken"]
    assert broken.problems and "nowhere" in " ".join(broken.problems)


def test_the_keepers_pages(tmp_path):
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP).replace("APPS", str(REPO / "applications")), encoding="utf-8"
    )
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/admin/keeper/"
        db = app.state.nest.bindings.get("nest.db")
        create_user(db, "ed@example.ro", "correct horse battery", roles=("editor",))
        create_user(db, "root@example.ro", "correct horse battery", roles=("admin",))
        c.get("/healthz")

        def sign_in(email):
            c.cookies.clear()
            c.get("/healthz")
            c.post(
                "/cont/login",
                data={
                    "csrf_token": c.cookies["nest_csrf"],
                    "email": email,
                    "password": "correct horse battery",
                },
            )

        sign_in("ed@example.ro")
        assert c.get("/admin/keeper/").status_code == 403  # the admin role only
        sign_in("root@example.ro")
        page = c.get("/admin/keeper/").text
        assert "Voievodate" in page or "voievodate" in page
        assert "/admin/keeper/app/gari" in page and ("runs" in page or "stopped" in page)
        detail = c.get("/admin/keeper/app/voievodate").text
        assert "Start order" in detail and "economy" in detail and "nest.db" in detail
        assert c.get("/admin/keeper/app/nowhere").status_code == 404
        packages = c.get("/admin/keeper/packages").text
        assert "subsystem" in packages and "nest.module.admin" in packages
