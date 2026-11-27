"""Installing packages into an application: only what this server's registry trusts, into
its pyproject.toml and module.yml (then uv sync), undone if that fails; removed only when
the application no longer uses it (nest.packages, the keeper's page)."""

import textwrap
import tomllib

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from test_keeper import APP as KEEPER
from test_registry import forum_range

from nest import create_app
from nest.manifest import load_manifest
from nest.packages import PackageError, add, read_registry, registry, remove, status

PYPROJECT = """
[project]
name = "site"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "nest-core>=0.2,<1",
    "nest-auth>=0.3,<1",
    "nest-admin>=0.1,<1",
]
"""

MANIFEST = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base}
deps:
  nest:
    auth: ">=0.3,<1"
    admin: ">=0.1,<1"
modules:
  - {name: auth, route: /cont, core: true}
  - {name: admin, route: /admin, core: true}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    root = tmp_path / "site"
    root.mkdir()
    (root / "pyproject.toml").write_text(textwrap.dedent(PYPROJECT).lstrip(), encoding="utf-8")
    (root / "module.yml").write_text(textwrap.dedent(MANIFEST).lstrip(), encoding="utf-8")
    monkeypatch.setenv("NEST_APP_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("NEST_REGISTRY", str(tmp_path / "none.yml"))
    return root


class Uv:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, args, cwd):
        self.calls.append((args, cwd))
        return (1, "resolution failed") if self.fail and len(self.calls) == 1 else (0, "ok")


def test_nests_own_packages_are_trusted():
    offers = registry()
    assert {"forum", "redis", "base"} <= set(offers)
    assert offers["forum"].dist == "nest-forum" and offers["forum"].path is not None
    assert offers["db"].interface == "nest.db"


def test_installing_adds_it_to_the_contract_installed_not_used(site):
    uv = Uv()
    add(site, "forum", runner=uv, say=lambda _l: None)
    assert uv.calls == [(["sync"], site)]
    project = tomllib.loads((site / "pyproject.toml").read_text())
    assert forum_range() in project["project"]["dependencies"]
    source = project["tool"]["uv"]["sources"]["nest-forum"]
    assert source["editable"] and source["path"].endswith("modules/forum")
    manifest = load_manifest(site)
    assert (
        manifest.deps["forum"] == forum_range().removeprefix("nest-forum")
        and manifest.dep_ecosystems["forum"] == "nest"
    )
    assert "forum" not in {i.name for i in manifest.modules}  # not used: the admin adds it
    rows = {r.offer.name: r for r in status(site)}
    assert rows["forum"].installed and rows["forum"].direct and not rows["forum"].used
    assert rows["htmx"].installed and not rows["htmx"].direct  # it comes with others
    assert rows["db"].used  # bound as nest.db
    with pytest.raises(PackageError, match="installed already"):
        add(site, "forum", runner=uv)


def test_a_failed_install_leaves_the_files_as_they_were(site):
    before = {p: (site / p).read_text() for p in ("pyproject.toml", "module.yml")}
    uv = Uv(fail=True)
    with pytest.raises(PackageError, match="uv sync failed"):
        add(site, "forum", runner=uv, say=lambda _l: None)
    assert {p: (site / p).read_text() for p in before} == before
    assert len(uv.calls) == 2  # and the environment synced back to them


def test_only_what_the_registry_trusts_and_the_application_does_not_use_is_touched(site):
    with pytest.raises(PackageError, match="not in this server's registry"):
        add(site, "anything-from-the-internet", runner=Uv())
    with pytest.raises(PackageError, match="uses auth"):
        remove(site, "auth", runner=Uv())
    with pytest.raises(PackageError, match="comes with"):
        remove(site, "htmx", runner=Uv())
    add(site, "forum", runner=Uv(), say=lambda _l: None)
    before = (site / "module.yml").read_text()
    remove(site, "forum", runner=Uv(), say=lambda _l: None)
    assert (
        "nest-forum"
        not in tomllib.loads((site / "pyproject.toml").read_text())["project"]["dependencies"]
    )
    assert "forum" not in load_manifest(site).deps and before != (site / "module.yml").read_text()


def test_a_registry_file_pins_what_it_trusts(tmp_path):
    good = tmp_path / "ok.yml"
    good.write_text(
        "packages:\n"
        "  - {name: shop, dist: nest-shop, version: '1.2.0', git: 'https://example.org/s.git',"
        " rev: '" + "a" * 40 + "'}\n"
        "  - {name: extra, dist: nest-extra, version: '2.0.1', index: 'https://pypi.org/simple'}\n",
        encoding="utf-8",
    )
    assert [o.name for o in read_registry(good)] == ["shop", "extra"]
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "packages:\n"
        "  - {name: shop, dist: nest-shop, version: '>=1.0', git: 'https://example.org/s.git', rev: main}\n"
        "  - {name: x, dist: nest-x, version: '1.0.0', index: 'http://insecure.example'}\n",
        encoding="utf-8",
    )
    with pytest.raises(PackageError) as e:
        read_registry(bad)
    text = "\n".join(e.value.problems)
    assert "exact version" in text and "pinned at a commit" in text and "an index is https" in text


def test_the_keeper_installs_from_its_page(site, tmp_path, monkeypatch):
    import nest.packages  # noqa: PLC0415

    uv = Uv()
    monkeypatch.setattr(nest.packages, "run_uv", uv)
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(KEEPER).replace("APPS", str(site)), encoding="utf-8"
    )
    app = create_app(
        root,
        environ={
            "NEST_APP_WORKSPACE": str(tmp_path / "kws"),
            "NEST_REGISTRY": str(tmp_path / "none.yml"),
        },
    )
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
        page = c.get("/admin/keeper/app/site/packages")
        assert page.status_code == 200 and "/admin/keeper/app/site/packages/forum/add" in page.text
        token = c.cookies["nest_csrf"]
        done = c.post("/admin/keeper/app/site/packages/forum/add", data={"csrf_token": token})
        assert done.status_code == 200 and "installed nest-forum" in done.text
        assert uv.calls and "nest-forum" in (site / "pyproject.toml").read_text()
        refused = c.post("/admin/keeper/app/site/packages/auth/remove", data={"csrf_token": token})
        assert refused.status_code == 400 and "uses auth" in refused.text


def test_the_keeper_searches_the_nest_registry_and_installs_from_it(site, tmp_path, monkeypatch):
    import nest.packages  # noqa: PLC0415
    from nest.packages import Offer  # noqa: PLC0415

    found = Offer(
        name="widgets", dist="acme-widgets", version="1.0.0", type="module", title="Widgets",
        description="Small widgets.", source="remote", index="https://r.example/simple/", nest=">=0.2,<1",
    )  # fmt: skip
    monkeypatch.setattr(nest.packages, "remote_offers", lambda environ=None: {"widgets": found})
    installed = []
    real_add = nest.packages.add
    monkeypatch.setattr(
        "nest.packages.add",
        lambda root, name, **kw: installed.append((name, kw.get("remote"))) or real_add,
    )
    root = tmp_path / "keeper"
    root.mkdir()
    (root / "module.yml").write_text(
        textwrap.dedent(KEEPER).replace("APPS", str(site)), encoding="utf-8"
    )
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "kws")})
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
        page = c.get("/admin/keeper/app/site/packages?q=widg").text
        assert "Widgets" in page and "/packages/widgets/add-remote" in page
        c.post(
            "/admin/keeper/app/site/packages/widgets/add-remote",
            data={"csrf_token": c.cookies["nest_csrf"]},
        )
        assert installed == [("widgets", True)]


def test_a_provider_brings_the_interfaces_it_implements(site):
    add(site, "redis", runner=Uv(), say=lambda _l: None)
    deps = tomllib.loads((site / "pyproject.toml").read_text())["project"]["dependencies"]
    assert {"nest-redis>=0.1,<1", "nest-cache>=0.2,<1", "nest-pubsub>=0.1,<1"} <= set(deps)
    manifest = load_manifest(site)
    assert {"redis", "cache", "pubsub"} <= set(manifest.deps)  # the app binds them: it names them
