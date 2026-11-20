"""Themes: several installed, one in use, chosen in the workspace (nest.themes); a theme
built on another; switched from the admin panel after a try, previewed by one
administrator alone; the theme contract."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from test_admin_modules import admin_client, register  # noqa: F401
from test_auth import post
from test_composition import APP

from nest import create_app
from nest.catalog import Catalog, Entry
from nest.composition import load_theme
from nest.manifest import load_manifest
from nest.themes import ThemeError, check_theme, themes, use


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    return root


def env(tmp_path):
    return {"NEST_APP_WORKSPACE": str(tmp_path / "ws")}


def page(app, path="/forum/"):
    with TestClient(app) as c:
        return c.get(path).text


def test_a_theme_built_on_another_takes_what_it_lacks_from_it(site, tmp_path):
    paper = create_app(site, environ=env(tmp_path), theme="paper")
    nest = paper.state.nest
    assert [t.name for t in nest.plan.themes] == ["paper", "base"]
    html = page(paper)
    assert 'class="site-header masthead"' in html  # paper's own layout
    files = [rel for _m, rel, _f in nest._style_files("site")]
    assert files.index("nest.css") < files.index("paper.css")  # base's, then paper's over it
    slate = page(create_app(site, environ=env(tmp_path), theme="slate"))
    assert 'class="container bar"' in slate and "masthead" not in slate  # base's layout


def test_the_administrator_chooses_and_it_is_kept_in_the_workspace(site, tmp_path):
    e = env(tmp_path)
    rows = {t.name: t for t in themes(site, e)}
    assert {"base", "paper", "slate"} <= set(rows) and rows["base"].active and rows["base"].default
    use(site, "paper", e, reload=False)
    assert load_theme(tmp_path / "ws") == "paper"
    assert "masthead" in page(create_app(site, environ=e))
    assert {t.name: t for t in themes(site, e)}["paper"].active
    use(site, None, e, reload=False)  # back to the manifest's
    assert load_theme(tmp_path / "ws") is None
    assert "masthead" not in page(create_app(site, environ=e))


def test_a_theme_that_cannot_show_the_pages_is_refused(site, tmp_path):
    e = env(tmp_path)
    with pytest.raises(ThemeError, match="not an installed theme"):
        use(site, "no-such-theme", e, reload=False)
    broken = site / "modules" / "broken"
    (broken / "templates").mkdir(parents=True)
    (broken / "module.yml").write_text(
        "module: {name: broken, id: test.theme.broken, type: theme, version: 0.1.0}\n"
        "extends: base\ndeps: {base: '>=0.2'}\n",
        encoding="utf-8",
    )
    (broken / "templates" / "layout.html").write_text(
        "{% block title %}{% endblock %}{% block head %}{% endblock %}{% block header %}{% endblock %}"
        "{% block nav %}{% endblock %}{% block language %}{% endblock %}{% block content %}{% endblock %}"
        "{% block footer %}{{ no_such_value.at_all }}{% endblock %}",  # every page shows it
        encoding="utf-8",
    )
    with pytest.raises(ThemeError, match="cannot show"):
        use(site, "broken", e, reload=False)
    assert load_theme(tmp_path / "ws") is None  # not kept


def test_the_theme_contract(tmp_path):
    known = list(Catalog.discover(None))
    for name in ("base", "paper", "slate"):
        entry = next(e for e in known if e.name == name)
        assert check_theme(entry, known) == [], name
    bare = tmp_path / "bare"
    (bare / "templates").mkdir(parents=True)
    (bare / "module.yml").write_text(
        "module: {name: bare, id: test.theme.bare, type: theme, version: 0.1.0}\n", encoding="utf-8"
    )
    (bare / "templates" / "layout.html").write_text(
        "{% block content %}{% endblock %}", encoding="utf-8"
    )
    entry = Entry(manifest=load_manifest(bare), source="local")
    problems = "\n".join(check_theme(entry, [*known, entry]))
    assert "has no error.html" in problems and "lacks the blocks: title, head" in problems


def test_from_the_admin_panel_previewed_then_used(site, tmp_path):
    c = admin_client(site, tmp_path)
    listing = c.get("/admin/themes")
    assert listing.status_code == 200
    assert "/admin/themes/paper/preview" in listing.text and "<svg" in listing.text
    assert (
        'style="' not in listing.text.split('<ul class="theme-list">')[1]
    )  # nothing the CSP refuses

    c.get("/admin/themes/paper/preview", follow_redirects=False)
    previewed = c.get("/forum/").text
    assert "masthead" in previewed and "theme-preview-bar" in previewed  # the site, in paper
    assert (
        'class="site-header masthead"' not in c.get("/admin/themes").text
    )  # the panel keeps its theme
    other = TestClient(c.app)  # another visitor: no preview
    assert "masthead" not in other.get("/forum/").text
    c.get("/admin/themes/preview/stop")
    assert "masthead" not in c.get("/forum/").text

    used = post(c, "/admin/themes/slate/use")
    assert used.status_code == 200 and "slate" in used.text
    assert load_theme(tmp_path / "ws") == "slate"
    refused = post(c, "/admin/themes/nothing/use")
    assert refused.status_code == 400
