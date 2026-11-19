"""Plug and play: an application's core modules and the others, chosen in its workspace,
enabled, disabled and uninstalled (nest.composition, nest.modules), and the boundaries a
package keeps so that this is safe (nest.boundaries)."""

import sqlite3
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nest import create_app
from nest.composition import Choice, CompositionError, compose, load, save
from nest.manifest import load_manifest
from nest.modules import ChangeError, change, status

APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base}
modules:
  - {name: auth, route: /cont, core: true}
  - {name: admin, route: /admin, core: true}
  - {name: comments, route: /comentarii}
  - {name: forum, route: /forum}
  - {name: redirects, enabled: false}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    return root


def env(tmp_path):
    return {"NEST_APP_WORKSPACE": str(tmp_path / "ws")}


def tables(tmp_path, prefix):
    with sqlite3.connect(tmp_path / "ws" / "data" / "app.db") as c:
        rows = c.execute("select name from sqlite_master where name like ?", (prefix + "%",))
        return sorted(r[0] for r in rows)


def test_the_workspace_choices_lie_over_the_manifest(site, tmp_path):
    manifest = load_manifest(site)
    choices = {"forum": Choice(False), "redirects": Choice(True), "glossary": Choice(True, "/d")}
    composed = {i.name: i for i in compose(manifest, choices)}
    assert not composed["forum"].enabled and composed["redirects"].enabled
    assert composed["glossary"].added and composed["glossary"].route == "/d"
    with pytest.raises(CompositionError, match="core module"):
        compose(manifest, {"auth": Choice(False)})
    save(tmp_path, choices)
    assert load(tmp_path) == choices


def test_status_says_what_is_core_locked_and_needed(site, tmp_path):
    rows = {r.name: r for r in status(site, env(tmp_path))}
    assert rows["auth"].state == "core" and rows["auth"].locked
    assert {"comments", "forum"} <= set(rows["auth"].needed_by)
    assert rows["forum"].state == "enabled" and not rows["forum"].locked
    assert rows["redirects"].state == "disabled" and rows["redirects"].data


def test_a_disabled_module_another_needs_is_refused_not_pulled_back(site, tmp_path):
    from nest.resolve import PlanError  # noqa: PLC0415

    (site / "module.yml").write_text(
        textwrap.dedent(APP).replace(
            "{name: auth, route: /cont, core: true}", "{name: auth, route: /cont, enabled: false}"
        ),
        encoding="utf-8",
    )
    with pytest.raises(PlanError, match="needs auth, which is disabled"):
        create_app(site, environ=env(tmp_path))


def test_core_modules_cannot_be_turned_off(site, tmp_path):
    with pytest.raises(ChangeError, match="auth is a core module"):
        change(site, env(tmp_path), disable=["auth"], reload=False)
    with pytest.raises(ChangeError, match="auth is a core module"):
        change(site, env(tmp_path), uninstall=["auth"], reload=False)


def test_disable_keeps_the_data_and_uninstall_removes_it(site, tmp_path):
    e = env(tmp_path)
    with TestClient(create_app(site, environ=e)) as c:
        assert c.get("/forum/").status_code == 200
    assert tables(tmp_path, "forum_")

    result = change(site, e, disable=["forum"], reload=False)
    assert result.backup is not None and result.backup.is_file()
    with TestClient(create_app(site, environ=e)) as c:
        assert c.get("/forum/").status_code == 404
    assert tables(tmp_path, "forum_")  # kept

    change(site, e, uninstall=["forum"], reload=False)
    assert tables(tmp_path, "forum_") == []  # its tables and version table gone

    change(site, e, enable=["forum"], reload=False)  # back, from nothing
    assert "forum_board" in tables(tmp_path, "forum_")
    with TestClient(create_app(site, environ=e)) as c:
        assert c.get("/forum/").status_code == 200


def test_a_module_can_be_added_with_a_route_and_its_settings_forgotten(site, tmp_path):
    e = env(tmp_path)
    with pytest.raises(ChangeError, match="give it a route"):
        change(site, e, enable=["messages"], reload=False)  # it serves pages, nowhere yet
    with pytest.raises(ChangeError, match="requires nest.search"):
        change(site, e, enable=["glossary"], routes={"glossary": "/d"}, reload=False)
    (site / "module.yml").write_text(
        textwrap.dedent(APP) + "  nest.search: {providers: [search-sqlite]}\n", encoding="utf-8"
    )
    change(site, e, enable=["glossary"], routes={"glossary": "/dictionar"}, reload=False)
    app = create_app(site, environ=e)
    app.state.nest.settings.set("glossary.per_page", 7)
    with TestClient(app) as c:
        assert c.get("/dictionar/").status_code == 200
    change(site, e, uninstall=["glossary"], reload=False)
    assert "glossary." not in (tmp_path / "ws" / "data" / "settings.conf").read_text()
    assert "glossary" not in load(tmp_path / "ws")  # added from the workspace: gone from it


def test_a_change_the_application_cannot_start_with_is_undone(site, tmp_path, monkeypatch):
    e = env(tmp_path)
    import nest_glossary  # noqa: PLC0415

    def broken(host):
        raise RuntimeError("broken on purpose")

    monkeypatch.setattr(nest_glossary, "setup", broken)
    (site / "module.yml").write_text(
        textwrap.dedent(APP) + "  nest.search: {providers: [search-sqlite]}\n", encoding="utf-8"
    )
    with pytest.raises(ChangeError, match="does not start that way"):
        change(site, e, enable=["glossary"], routes={"glossary": "/d"}, reload=False)
    assert "glossary" not in load(tmp_path / "ws")  # the old composition is back
    assert tables(tmp_path, "glossary_") == []  # and the tables made for it are gone


def test_an_optional_module_that_fails_is_left_out_whole(site, tmp_path, monkeypatch):
    (site / "module.yml").write_text(
        textwrap.dedent(APP).replace(
            "{name: forum, route: /forum}", "{name: forum, route: /forum, optional: true}"
        ),
        encoding="utf-8",
    )
    import nest_forum  # noqa: PLC0415

    real = nest_forum.setup

    def half(host):
        real(host)  # registers its routes, topics, filters...
        raise RuntimeError("then fails")

    monkeypatch.setattr(nest_forum, "setup", half)
    app = create_app(site, environ=env(tmp_path))
    nest = app.state.nest
    assert nest.states["forum"].state == "degraded" and "then fails" in nest.states["forum"].reason
    with TestClient(app) as c:
        assert c.get("/forum/").status_code == 404  # nothing it registered stayed
        assert c.get("/comentarii/").status_code != 500


def test_settings_read_live_apply_at_once(site, tmp_path):
    app = create_app(site, environ=env(tmp_path))
    nest = app.state.nest
    state = nest.module_state["forum"]
    before = state["posts_per_page"]
    nest.settings.set("forum.posts_per_page", before + 5)
    assert state["posts_per_page"] == before + 5  # no restart
    assert state.get("posts_per_page") == before + 5


def test_the_packages_keep_their_boundaries():
    from nest.boundaries import check  # noqa: PLC0415
    from nest.catalog import Catalog, Entry  # noqa: PLC0415

    repo = Path(__file__).resolve().parents[1]
    entries = []
    for folder in ("modules", "interfaces", "providers", "themes", "engines"):
        for manifest in sorted((repo / folder).rglob("module.yml")):
            if ".venv" in manifest.parts:
                continue
            entries.append(Entry(manifest=load_manifest(manifest.parent), source="local"))
    errors = [f for f in check(entries, [*Catalog.discover(None), *entries]) if f.level == "error"]
    assert errors == [], "\n".join(map(str, errors))


def test_the_checker_sees_a_package_reaching_in(tmp_path):
    from nest.boundaries import check  # noqa: PLC0415
    from nest.catalog import Catalog, Entry  # noqa: PLC0415

    root = tmp_path / "nosy"
    (root / "nosy").mkdir(parents=True)
    (root / "module.yml").write_text(
        "module: {name: nosy, id: test.module.nosy, type: module, version: 0.1.0}\n"
        "main: nosy\ndeps: {auth: '>=0.1'}\n",
        encoding="utf-8",
    )
    (root / "nosy" / "__init__.py").write_text(
        "from nest_auth.sessions import open_session\n"
        "from nest_auth import secret_thing\n"
        "import nest_forum\n"
        "def f(request, host):\n"
        "    from nest_seo import head\n"
        "    module_state(request, 'media')\n"
        "    return host._nest\n",
        encoding="utf-8",
    )
    entry = Entry(manifest=load_manifest(root), source="local")
    found = check([entry], [*Catalog.discover(None), entry])
    text = "\n".join(f.message for f in found)
    assert "reaches into auth's internals (nest_auth.sessions)" in text
    assert "uses auth.secret_thing, which auth does not export" in text
    assert "imports forum without depending on it" in text
    assert "uses seo without depending on it" in text  # a warning: lazy, optional
    assert "reads media's run-time state" in text
    assert "host's private _nest" in text
