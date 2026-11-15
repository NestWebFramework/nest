import pytest
from conftest import module_yml

from nest.catalog import Catalog, Entry
from nest.contract import load_contracts
from nest.manifest import load_manifest
from nest.resolve import PlanError, plan


def make_plan(root):
    app = Entry(manifest=load_manifest(root), source="application")
    return plan(app, Catalog.discover(root), load_contracts())


APP = module_yml(
    "demo",
    "application",
    extra="""
    application:
      port: 8000
    modules:
      - name: blog
        route: /blog
""",
)


def test_dependencies_start_first_and_order_is_stable(app_dir):
    root = app_dir(
        {
            "module.yml": APP,
            "modules/blog/module.yml": module_yml(
                "blog", extra="deps:\n  parts: '>=0.1'\n  markdown: ''\n"
            ),
            "modules/parts/module.yml": module_yml("parts", extra="deps:\n  markdown: ''\n"),
            "modules/markdown/module.yml": module_yml("markdown"),
        }
    )
    the_plan = make_plan(root)
    assert [u.name for u in the_plan.units] == ["markdown", "parts", "blog"]
    assert the_plan.unit("blog").instance.route == "/blog"
    assert the_plan.unit("parts").instance is None


def test_every_problem_is_reported_at_once(app_dir):
    root = app_dir(
        {
            "module.yml": APP,
            "modules/blog/module.yml": module_yml(
                "blog",
                extra="""
            deps:
              parts: '>=2'
              missing: ''
            requires:
              host: [teleporter]
              interfaces: [nest.search]
        """,
            ),
            "modules/parts/module.yml": module_yml("parts", version="1.0.0"),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "blog needs parts >=2, but 1.0.0 is installed" in text
    assert "blog depends on 'missing', which is not installed" in text
    assert "host facility 'teleporter'" in text
    assert "blog requires nest.search; bind it in demo's module.yml" in text


def test_an_applications_deps_are_its_contract(app_dir):
    def app(deps):
        return module_yml(
            "demo",
            "application",
            extra=f"""
    application:
      port: 8000
    modules:
      - name: blog
        route: /blog
    deps:
{deps}
""",
        )

    files = {"modules/blog/module.yml": module_yml("blog", version="1.2.0")}
    kept = make_plan(app_dir({"module.yml": app("      nest:\n        blog: '>=1.2,<2'"), **files}))
    assert [u.name for u in kept.units] == ["blog"]
    with pytest.raises(PlanError) as e:
        make_plan(
            app_dir(
                {
                    "module.yml": app(
                        "      nest:\n        blog: '>=2'\n        gone: '>=1'\n      parts: '>=1'"
                    ),
                    **files,
                }
            )
        )
    text = str(e.value)
    assert "demo needs blog >=2, but 1.2.0 is installed" in text
    assert "demo depends on 'gone', which is not installed" in text
    assert "demo depends on 'parts' without saying whose" in text


def test_an_applications_deps_name_each_ecosystem_and_every_package(app_dir):
    root = app_dir(
        {
            "module.yml": module_yml(
                "demo",
                "application",
                extra="""
    application: {port: 8000, theme: base}
    deps:
      saga:
        blog: '>=0.1'
    modules:
      - name: blog
        route: /blog
""",
            ),
            "modules/blog/module.yml": module_yml("blog"),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "demo uses 'base' but its deps give no version range for it" in text
    assert "demo lists 'blog' under saga, but it is nest's" in text


def test_a_cycle_is_named(app_dir):
    root = app_dir(
        {
            "module.yml": APP,
            "modules/blog/module.yml": module_yml("blog", extra="deps:\n  a: ''\n"),
            "modules/a/module.yml": module_yml("a", extra="deps:\n  b: ''\n"),
            "modules/b/module.yml": module_yml("b", extra="deps:\n  a: ''\n"),
        }
    )
    with pytest.raises(PlanError, match="a dependency cycle joins: a, b, blog"):
        make_plan(root)


def test_a_former_id_still_resolves_with_a_note(app_dir):
    root = app_dir(
        {
            "module.yml": APP.replace("name: blog", "name: test.module.oldblog"),
            "modules/blog/module.yml": module_yml("blog").replace(
                "type: module", "type: module\n  previous_ids: [test.module.oldblog]"
            ),
        }
    )
    the_plan = make_plan(root)
    assert [u.name for u in the_plan.units] == ["blog"]
    assert "former id" in the_plan.notes[0]


def test_only_modules_are_mounted_and_need_a_route(app_dir):
    root = app_dir(
        {
            "module.yml": module_yml(
                "demo",
                "application",
                extra="""
            application: {port: 8000}
            modules:
              - name: blog
              - name: cache-memory
                route: /c
        """,
            ),
            "modules/blog/module.yml": module_yml("blog"),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    assert "'cache-memory' is a provider, not a module" in str(e.value)
    assert "includes 'blog' without a route" in str(e.value)


def test_bindings_are_checked_against_installed_interfaces(app_dir):
    root = app_dir(
        {
            "module.yml": module_yml(
                "demo",
                "application",
                extra="""
            application: {port: 8000}
            bind:
              nest.cache:
                providers: [cache-memory]
                config:
                  redis: {url: x}
              nest.nothing:
                providers: [cache-memory]
        """,
            ),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "configures 'redis' for nest.cache, but does not bind it" in text
    assert "binds 'nest.nothing', but no installed interface has that name" in text


def test_a_name_claimed_twice_stops_the_plan(app_dir):
    root = app_dir(
        {
            "module.yml": APP,
            "modules/blog/module.yml": module_yml("blog", extra="deps:\n  htmx: ''\n"),
            "modules/htmx/module.yml": module_yml("htmx"),  # an installed package has this name
        }
    )
    with pytest.raises(PlanError, match="two packages are named 'htmx'.*rename one"):
        make_plan(root)


def test_a_disabled_module_is_left_out(app_dir):
    root = app_dir(
        {
            "module.yml": APP.replace("route: /blog", "route: /blog\n    enabled: false"),
        }
    )
    assert make_plan(root).units == []


def test_a_part_joins_the_host_it_names(app_dir):
    host = module_yml("engine", extra="subsystems:\n  types: [module]\n  bundled: [wheel]\n")
    wheel = module_yml("wheel", extra="part_of: engine\ndeps:\n  engine: '>=0.1'\n")
    app = module_yml(
        "demo",
        "application",
        extra="""
    application: {port: 8000}
    modules:
      - {name: engine, route: /e}
      - {name: wheel, route: /w}
""",
    )
    kept = make_plan(
        app_dir(
            {
                "module.yml": app,
                "modules/engine/module.yml": host,
                "modules/wheel/module.yml": wheel,
            }
        )
    )
    assert [u.name for u in kept.units] == ["engine", "wheel"]
    assert kept.unit("engine").entry.manifest.subsystems.bundled == ["wheel"]


def test_a_part_without_its_host_or_unwelcome_there_is_refused(app_dir):
    app = module_yml(
        "demo",
        "application",
        extra="""
    application: {port: 8000}
    modules:
      - {name: plain, route: /p}
      - {name: stray, route: /s}
      - {name: orphan, route: /o}
""",
    )
    root = app_dir(
        {
            "module.yml": app,
            "modules/plain/module.yml": module_yml("plain"),
            "modules/stray/module.yml": module_yml("stray", extra="part_of: plain\n"),
            "modules/orphan/module.yml": module_yml("orphan", extra="part_of: gone\n"),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "stray is part of 'plain', which takes no parts" in text
    assert "stray is part of 'plain' but does not depend on it (deps)" in text
    assert "orphan is part of 'gone', which demo does not include" in text


def test_a_stylesheet_named_must_be_there(app_dir):
    app = module_yml(
        "demo",
        "application",
        extra="application: {port: 8000}\nmodules:\n  - {name: blog, route: /b}\n",
    )
    blog = module_yml("blog", extra="styles: [blog.css, gone.css]\n")
    root = app_dir(
        {"module.yml": app, "modules/blog/module.yml": blog, "modules/blog/static/blog.css": "p {}"}
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "blog names the stylesheet 'gone.css', which its static folder lacks" in text
    assert "'blog.css'" not in text
