"""Themes: several installed, one in use, chosen in the workspace (nest.themes); a theme
built on another; switched from the admin panel after a try, previewed by one
administrator alone; the theme contract."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from test_admin_modules import admin_client, register  # noqa: F401
from test_auth import post
from test_admin_modules import APP

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


def test_a_layout_may_extend_a_frame_its_themes_share(tmp_path):
    known = list(Catalog.discover(None))
    blocks = "".join(
        f"{{% block {b} %}}{{% endblock %}}"
        for b in ("lang", "title", "head", "header", "nav", "language", "content", "footer")
    ) + "{{ nest_credit }}"

    def theme(name, extends, files):
        root = tmp_path / name
        for rel, text in files.items():
            (root / "templates" / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "templates" / rel).write_text(text, encoding="utf-8")
        (root / "module.yml").write_text(
            f"module: {{name: {name}, id: test.theme.{name}, type: theme, version: 0.1.0}}\n"
            f"extends: {extends}\ndeps: {{{extends}: '>=0'}}\n",
            encoding="utf-8",
        )
        return Entry(manifest=load_manifest(root), source="local")

    village = theme(
        "village",
        "base",
        {"frame/page.html": blocks, "layout.html": '{% extends "frame/page.html" %}'},
    )
    almanac = theme(
        "almanac",
        "village",
        {"layout.html": '{% extends "frame/page.html" %}{% block header %}A{% endblock %}'},
    )
    world = [*known, village, almanac]
    assert check_theme(village, world) == [] and check_theme(almanac, world) == []
    thin = theme(
        "thin",
        "base",
        {
            "frame/page.html": "{% block content %}{% endblock %}",
            "layout.html": '{% extends "frame/page.html" %}',
        },
    )
    problems = "\n".join(check_theme(thin, [*known, thin]))
    assert "lacks the blocks: title" in problems
    assert "does not show {{ nest_credit }}" in problems  # every site says it is built with Nest


def test_every_site_says_it_is_built_with_nest(tmp_path):
    from fastapi.testclient import TestClient

    from nest import create_app

    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(
        "module: {name: sat, id: test.app.sat, type: application, version: 0.1.0}\n"
        "application: {title: Sat, port: 8000, theme: base, languages: [ro, en], language_urls: prefix}\n"
        "modules:\n  - {name: auth, route: /cont}\n"
        "bind:\n  nest.db: {providers: [db-sqlite]}\n",
        encoding="utf-8",
    )
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        ro, en = c.get("/cont/login").text, c.get("/en/cont/login").text
        assert 'Construit cu platforma <a href="https://nest-framework.org"' in ro
        assert 'Built with the <a href="https://nest-framework.org"' in en


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


def test_a_theme_has_settings_the_application_sets_and_its_children_share(tmp_path):
    """theme_setting(): the theme's, else the one it is built on (the first set along the
    chain); application.theme_settings sets them; module_url(): a module where it is."""
    root = tmp_path / "app"
    for name, extends, settings in (
        ("parent", "base", "settings:\n  tagline: {default: ''}\n  credit: {default: 'nobody'}\n"),
        ("child", "parent", "settings:\n  tagline: {default: ''}\n"),
    ):
        folder = root / "modules" / name
        (folder / "templates").mkdir(parents=True)
        (folder / "module.yml").write_text(
            f"module: {{name: {name}, id: test.theme.{name}, type: theme, version: 0.1.0}}\n"
            f"extends: {extends}\ndeps: {{{extends}: '>=0'}}\n{settings}",
            encoding="utf-8",
        )
    (root / "module.yml").write_text(
        "module: {name: app, id: test.app.themed, type: application, version: 0.1.0}\n"
        "application:\n  port: 8000\n  theme: child\n"
        "  theme_settings: {parent: {tagline: 'From the parent', credit: 'me'}}\n"
        "modules:\n  - {name: auth, route: /cont}\n"
        "bind:\n  nest.db: {providers: [db-sqlite]}\n",
        encoding="utf-8",
    )
    nest = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}).state.nest
    assert nest.theme_setting("tagline") == "From the parent"  # the child's is empty: the parent's
    assert nest.theme_setting("credit") == "me" and nest.theme_setting("nothing", "x") == "x"
    nest.settings.set("child.tagline", "The child's own")
    assert nest.theme_setting("tagline") == "The child's own"
    assert nest.module_url("auth") == "/cont/" and nest.module_url("auth", "login") == "/cont/login"
    assert nest.module_url("gallery") is None


def test_the_themes_settings_are_one_tab_with_a_tab_each_under_it(tmp_path):
    """Settings: a tab per module, one for the themes; under it a tab per installed theme
    with settings (the one in use first), set even before it is used. The Themes page has
    a Settings button beside Preview."""
    root = tmp_path / "app"
    for name, title in (("meadow", "Meadow"), ("hill", "Hill")):
        folder = root / "modules" / name
        (folder / "templates").mkdir(parents=True)
        (folder / "module.yml").write_text(
            f"module: {{name: {name}, id: test.theme.{name}, type: theme, version: 0.1.0, title: {title}}}\n"
            "extends: base\ndeps: {base: '>=0'}\nsettings:\n  tagline: {label: Tagline, default: ''}\n",
            encoding="utf-8",
        )
    (root / "module.yml").write_text(
        "module: {name: app, id: test.app.tabs, type: application, version: 0.1.0}\n"
        "application:\n  port: 8000\n  theme: meadow\n  theme_settings: {hill: {tagline: 'On the hill'}}\n"
        "modules:\n  - {name: auth, route: /cont}\n  - {name: admin, route: /admin}\n"
        "bind:\n  nest.db: {providers: [db-sqlite]}\n",
        encoding="utf-8",
    )
    c = admin_client(root, tmp_path)
    page = c.get("/admin/settings/auth").text
    top = page.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    assert "/admin/settings/themes" in top and "/admin/settings/meadow" not in top
    assert "subtabs" not in page  # a module's section: no themes' tabs
    r = c.get("/admin/settings/themes", follow_redirects=False)
    assert r.headers["location"] == "/admin/settings/meadow"  # the theme in use
    themes_page = c.get("/admin/settings/hill").text
    under = themes_page.split('class="tabs subtabs"', 1)[1].split("</nav>", 1)[0]
    assert under.index("meadow") < under.index("hill")
    assert 'value="On the hill"' in themes_page  # what the application sets, before it is used
    assert post(c, "/admin/settings/hill", **{"hill.tagline": "Higher"}).status_code == 303
    assert c.app.state.nest.settings.get("hill.tagline") == "Higher"
    listing = c.get("/admin/themes").text
    assert 'href="/admin/settings/hill"' in listing and 'href="/admin/settings/meadow"' in listing
    assert 'href="/admin/settings/paper"' not in listing  # no settings, no button
