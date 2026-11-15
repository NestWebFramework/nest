"""The keeper: Nest's applications, their plans and problems, whether they run, the packages."""

import textwrap
from pathlib import Path

import pytest
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
    assert {"gari", "morlaca", "transilpedia", "regionalisme", "keeper"} <= set(apps)
    assert "voievodate" not in apps  # the game lives in a repo of its own


GAME = REPO.parent / "voievodate"  # voievodate's repo, checked out beside nest


@pytest.mark.skipif(not (GAME / "module.yml").exists(), reason="no voievodate checkout")
def test_a_game_in_its_own_repo_is_found_and_planned():
    apps = {a.name: a for a in applications([REPO / "applications", GAME])}
    voievodate = apps["voievodate"]
    assert voievodate.port == 8500 and not voievodate.problems, voievodate.problems
    names = [u["name"] for u in voievodate.units]
    assert names.index("saga") < names.index("npc") and {
        "admin",
        "economy",
        "voievodate-content",
    } <= set(names)
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


@pytest.mark.skipif(not (GAME / "module.yml").exists(), reason="no voievodate checkout")
def test_the_keepers_pages(tmp_path):
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP).replace("APPS", f"{REPO / 'applications'},{GAME}"), encoding="utf-8"
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


def make_keeper(tmp_path):
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(APP).replace("APPS", f"{REPO / 'applications'},{GAME}"), encoding="utf-8"
    )
    return create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


@pytest.mark.skipif(not (GAME / "module.yml").exists(), reason="no voievodate checkout")
def test_the_rest_api_answers_only_to_a_token(tmp_path):
    from nest_keeper import rest as keeper_api
    from nest_keeper import tokens
    from nest_keeper.models import KeeperToken
    from sqlalchemy import select

    keeper_api._failures.clear()
    app = make_keeper(tmp_path)
    db = app.state.nest.bindings.get("nest.db")
    secret, t = tokens.create(db, "orchestrator")
    with TestClient(app) as c:
        assert c.get("/api/v1/apps").status_code == 401
        assert c.get("/api/v1/apps").headers["www-authenticate"].startswith("Bearer")
        assert (
            c.get("/api/v1/apps", headers={"Authorization": "Bearer nk_wrong"}).status_code == 401
        )
        auth = {"Authorization": f"Bearer {secret}"}
        r = c.get("/api/v1/", headers=auth)
        assert (
            r.status_code == 200
            and r.json()["token"]["name"] == "orchestrator"
            and r.headers["cache-control"] == "no-store"
        )
        eco = c.get("/api/v1/ecosystem", headers=auth).json()
        assert (
            eco["name"] == "nest"
            and eco["kind"] == "web"
            and {"module", "application", "subsystem"} <= set(eco["types"])
        )
        apps = {a["name"]: a for a in c.get("/api/v1/apps", headers=auth).json()["apps"]}
        assert apps["voievodate"]["port"] == 8500 and apps["voievodate"]["running"] in (True, False)
        one = c.get("/api/v1/apps/voievodate", headers=auth).json()
        assert one["bindings"] == {"nest.db": ["db-sqlite"]} and any(
            u["name"] == "economy" for u in one["units"]
        )
        assert c.get("/api/v1/apps/nowhere", headers=auth).status_code == 404
        assert any(
            p["name"] == "keeper"
            for p in c.get("/api/v1/packages", headers=auth).json()["packages"]
        )
        with db.session() as s:
            row = s.scalar(select(KeeperToken))
            assert (
                row.digest != secret
                and secret not in row.prefix + row.digest
                and row.last_used_at is not None
            )
        tokens.revoke(db, t.id)
        assert c.get("/api/v1/", headers=auth).status_code == 401
        for _ in range(25):
            c.get("/api/v1/", headers={"Authorization": "Bearer nk_guess"})
        assert c.get("/api/v1/", headers={"Authorization": "Bearer nk_guess"}).status_code == 429
    keeper_api._failures.clear()


def test_tokens_in_the_panel_are_shown_once(tmp_path):
    from nest_keeper import rest as keeper_api

    keeper_api._failures.clear()
    app = make_keeper(tmp_path)
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"),
            "root@example.ro",
            "correct horse battery",
            roles=("admin",),
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "root@example.ro",
                "password": "correct horse battery",
            },
        )
        h = {"X-CSRF-Token": c.cookies["nest_csrf"]}
        page = c.post("/admin/keeper/tokens", data={"name": "orchestrator"}, headers=h).text
        import re

        (secret,) = re.findall(r"<code>(nk_[A-Za-z0-9_-]{20,})</code>", page)
        assert secret not in c.get("/admin/keeper/tokens").text  # never shown again
        assert c.get("/api/v1/", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
        assert c.get("/api/v1/").status_code == 401  # a signed-in browser's cookie is not a token
        c.post("/admin/keeper/tokens/1/revoke", headers=h)
        assert c.get("/api/v1/", headers={"Authorization": f"Bearer {secret}"}).status_code == 401
        assert c.post("/admin/keeper/tokens", data={"name": ""}, headers=h).status_code == 400
