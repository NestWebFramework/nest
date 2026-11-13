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
                "blog", extra="deps:\n  forms: '>=0.1'\n  markdown: ''\n"
            ),
            "modules/forms/module.yml": module_yml("forms", extra="deps:\n  markdown: ''\n"),
            "modules/markdown/module.yml": module_yml("markdown"),
        }
    )
    the_plan = make_plan(root)
    assert [u.name for u in the_plan.units] == ["markdown", "forms", "blog"]
    assert the_plan.unit("blog").instance.route == "/blog"
    assert the_plan.unit("forms").instance is None


def test_every_problem_is_reported_at_once(app_dir):
    root = app_dir(
        {
            "module.yml": APP,
            "modules/blog/module.yml": module_yml(
                "blog",
                extra="""
            deps:
              forms: '>=2'
              missing: ''
            requires:
              host: [teleporter]
              interfaces: [nest.search]
        """,
            ),
            "modules/forms/module.yml": module_yml("forms", version="1.0.0"),
        }
    )
    with pytest.raises(PlanError) as e:
        make_plan(root)
    text = str(e.value)
    assert "blog needs forms >=2, but 1.0.0 is installed" in text
    assert "blog depends on 'missing', which is not installed" in text
    assert "host facility 'teleporter'" in text
    assert "blog requires nest.search; bind it in demo's module.yml" in text


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


def test_a_disabled_module_is_left_out(app_dir):
    root = app_dir(
        {
            "module.yml": APP.replace("route: /blog", "route: /blog\n    enabled: false"),
        }
    )
    assert make_plan(root).units == []
