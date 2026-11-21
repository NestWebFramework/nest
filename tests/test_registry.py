"""The Nest registry (registry.nest-framework.org): publishing with a token, the rules a
publish keeps, the Python index uv installs from, the catalog, and the client side
(nest login, nest publish, nest packages add --remote)."""

import hashlib
import io
import tarfile
import textwrap
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_registry import service

from nest import create_app

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "applications" / "registry"


def manifest(name="widgets", id_="acme.module.widgets", version="1.0.0", nest='">=0.2,<1"'):
    return textwrap.dedent(f"""
        module: {{name: {name}, id: {id_}, type: module, version: {version}, title: Widgets,
                 description: Small widgets for pages.}}
        {"nest: " + nest if nest else ""}
        main: acme_{name}
        deps: {{auth: ">=0.3,<1"}}
        uses: [seo]
    """)


def wheel(
    dist="acme-widgets", version="1.0.0", pkg="acme_widgets", module_yml=None, meta_version=None
):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{pkg}/__init__.py", "")
        if module_yml is not False:
            z.writestr(f"{pkg}/module.yml", module_yml or manifest(version=version))
        info = f"{dist.replace('-', '_')}-{version}.dist-info"
        z.writestr(
            f"{info}/METADATA",
            f"Metadata-Version: 2.3\nName: {dist}\nVersion: {meta_version or version}\nRequires-Python: >=3.12\n",
        )
    return f"{dist.replace('-', '_')}-{version}-py3-none-any.whl", buf.getvalue()


@pytest.fixture
def registry(tmp_path):
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    db = app.state.nest.bindings.get("nest.db")
    with TestClient(app) as c:
        admin = create_user(db, "root@example.org", "correct horse battery", roles=("admin",))
        ada = create_user(db, "ada@example.org", "correct horse battery", roles=("publisher",))
        bob = create_user(db, "bob@example.org", "correct horse battery", roles=("publisher",))
        eve = create_user(db, "eve@example.org", "correct horse battery")  # no publisher role
        people = (("admin", admin), ("ada", ada), ("bob", bob), ("eve", eve))
        tokens = {who: service.make_token(db, u.id, "test")[0] for who, u in people}
        c.users = dict(people)
        yield c, tokens


def up(c, token, name, data):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return c.post(
        "/api/v1/upload", files={"file": (name, data, "application/octet-stream")}, headers=headers
    )


def test_a_publisher_publishes_and_uv_finds_it_in_the_index(registry):
    c, tokens = registry
    name, data = wheel()
    r = up(c, tokens["ada"], name, data)
    assert r.status_code == 201, r.text
    sha = hashlib.sha256(data).hexdigest()
    assert r.json()["sha256"] == sha and r.json()["url"].endswith("/p/widgets")
    root = c.get("/simple/")
    assert 'href="acme-widgets/"' in root.text
    page = c.get("/simple/acme-widgets/")
    assert (
        f"/files/{sha}/{name}#sha256={sha}" in page.text
        and 'data-requires-python="&gt;=3.12"' in page.text
    )
    js = c.get("/simple/acme-widgets/", headers={"accept": "application/vnd.pypi.simple.v1+json"})
    assert js.headers["content-type"].startswith("application/vnd.pypi.simple.v1+json")
    assert js.json()["files"][0]["hashes"]["sha256"] == sha
    assert c.get("/simple/Acme_Widgets/", follow_redirects=False).status_code == 301  # PEP 503
    got = c.get(f"/files/{sha}/{name}")
    assert got.content == data and "immutable" in got.headers["cache-control"]
    item = c.get("/api/v1/packages/widgets").json()
    assert (
        item["type"] == "module"
        and item["nest"] == ">=0.2,<1"
        and item["deps"] == ["auth"]
        and item["uses"] == ["seo"]
    )
    assert c.get("/api/v1/packages?q=small").json()["packages"][0]["name"] == "widgets"
    assert "Widgets" in c.get("/p/widgets").text and "Widgets" in c.get("/?q=widg").text


def test_what_a_publish_must_keep(registry):
    c, tokens = registry
    assert up(c, None, *wheel()).status_code == 401
    assert up(c, "nrt_not-a-token", *wheel()).status_code == 401
    r = up(c, tokens["ada"], *wheel(module_yml=False))
    assert r.status_code == 400 and "no module.yml" in r.json()["detail"]
    r = up(c, tokens["ada"], *wheel(module_yml=manifest(nest=None)))
    assert r.status_code == 400 and "nest-core versions" in r.json()["detail"]
    r = up(c, tokens["ada"], *wheel(module_yml=manifest(version="1.0.1")))
    assert r.status_code == 400 and "says 1.0.1, the wheel 1.0.0" in r.json()["detail"]
    official = manifest(name="forum2", id_="nest.module.forum2")
    r = up(c, tokens["ada"], *wheel(dist="nest-forum2", pkg="acme_forum2", module_yml=official))
    assert r.status_code == 403 and "administrators" in r.json()["detail"]
    assert (
        up(
            c, tokens["admin"], *wheel(dist="nest-forum2", pkg="acme_forum2", module_yml=official)
        ).status_code
        == 201
    )

    assert up(c, tokens["ada"], *wheel()).status_code == 201
    again = up(c, tokens["ada"], *wheel())
    assert again.status_code == 409 and "a fix is a new version" in again.json()["detail"]
    theirs = up(c, tokens["bob"], *wheel(version="1.1.0"))
    assert theirs.status_code == 403 and "another account" in theirs.json()["detail"]
    assert up(c, tokens["ada"], *wheel(version="1.1.0")).status_code == 201  # the owner's next


def test_a_source_archive_follows_its_wheel(registry):
    c, tokens = registry
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("acme_widgets-1.0.0/PKG-INFO")
        body = b"Name: acme-widgets\nVersion: 1.0.0\n"
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    sdist = ("acme_widgets-1.0.0.tar.gz", buf.getvalue())
    r = up(c, tokens["ada"], *sdist)
    assert r.status_code == 400 and "before its source archive" in r.json()["detail"]
    up(c, tokens["ada"], *wheel())
    assert up(c, tokens["ada"], *sdist).status_code == 201
    assert "acme_widgets-1.0.0.tar.gz" in c.get("/simple/acme-widgets/").text


def test_tokens_are_made_in_the_browser_shown_once_and_revoked(tmp_path):
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"),
            "ada@example.org",
            "correct horse battery",
            roles=("publisher",),
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ada@example.org",
                "password": "correct horse battery",
            },
        )
        made = c.post("/tokens", data={"csrf_token": c.cookies["nest_csrf"], "name": "laptop"})
        import re  # noqa: PLC0415

        (secret,) = set(re.findall(r"(nrt_[A-Za-z0-9_-]{30,})", made.text))
        assert secret not in c.get("/tokens").text
        assert (
            c.get("/api/v1/whoami", headers={"Authorization": f"Bearer {secret}"}).json()["account"]
            == "ada@example.org"
        )
        token_id = service.tokens_of(app.state.nest.bindings.get("nest.db"), 1)[0].id
        c.post(f"/tokens/{token_id}/revoke", data={"csrf_token": c.cookies["nest_csrf"]})
        assert (
            c.get("/api/v1/whoami", headers={"Authorization": f"Bearer {secret}"}).status_code
            == 401
        )


def test_nest_publish_then_install_from_the_registry(registry, tmp_path, monkeypatch):
    """The client side, against the registry: login, publish a real package (built by uv),
    then add it to an application from the index."""
    import nest.remote as remote  # noqa: PLC0415
    from nest.packages import add  # noqa: PLC0415

    c, tokens = registry

    def client(url, token=None):
        c.headers.clear()
        if token:
            c.headers["Authorization"] = f"Bearer {token}"
        return _Same(c)

    monkeypatch.setattr(remote, "_client", client)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    url = "https://registry.example.org"
    assert remote.login(url, tokens["admin"]) == "root@example.org"
    stored = tmp_path / "config" / "nest" / "credentials.yml"
    assert oct(stored.stat().st_mode)[-3:] == "600"

    done = remote.publish(REPO / "modules" / "forum", url, say=lambda _l: None)
    assert [d["file"].split("-")[0] for d in done] == ["nest_forum", "nest_forum"]  # wheel, sdist
    assert c.get("/api/v1/packages/forum").json()["type"] == "module"

    site = tmp_path / "site"
    site.mkdir()
    (site / "pyproject.toml").write_text(
        '[project]\nname = "site"\nversion = "0.1.0"\ndependencies = [\n    "nest-core>=0.2,<1",\n]\n\n'
        '[tool.uv.sources]\nnest-forum = { path = "../nest/modules/forum", editable = true }\n',
        encoding="utf-8",
    )
    (site / "module.yml").write_text(
        "module: {name: site, id: test.app.site, type: application, version: 0.1.0}\n"
        'application: {title: Site, port: 8000, theme: base}\ndeps:\n  nest:\n    base: ">=0.2,<1"\n',
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setenv("NEST_REGISTRY_URL", url)
    add(
        site,
        "forum",
        remote=True,
        runner=lambda a, cwd: calls.append(a) or (0, ""),
        say=lambda _l: None,
    )
    project = tomllib.loads((site / "pyproject.toml").read_text())
    assert "nest-forum>=0.1,<1" in project["project"]["dependencies"]
    assert project["tool"]["uv"]["index"] == [{"name": "nest", "url": f"{url}/simple/"}]
    assert project["tool"]["uv"]["sources"]["nest-forum"] == {
        "index": "nest"
    }  # not the path any more
    assert calls == [["sync"]]


class _Same:
    """The test client as the context manager nest.remote opens."""

    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, *exc):
        return False


# --- who may publish -----------------------------------------------------------------------


def test_only_approved_publishers_publish(registry):
    c, tokens = registry
    r = up(c, tokens["eve"], *wheel())
    assert r.status_code == 403 and "administrators approve publishers" in r.json()["detail"]
    me = c.get("/api/v1/whoami", headers={"Authorization": f"Bearer {tokens['eve']}"}).json()
    assert me["may_publish"] is False
    c.app.state.nest.settings.set("registry.publishers", "anyone")  # an open registry
    assert up(c, tokens["eve"], *wheel()).status_code == 201


def test_a_namespace_is_its_first_publishers(registry):
    c, tokens = registry
    assert up(c, tokens["ada"], *wheel()).status_code == 201  # acme.module.widgets: acme is ada's
    gadgets = manifest(name="gadgets", id_="acme.module.gadgets")
    r = up(c, tokens["bob"], *wheel(dist="acme-gadgets", pkg="acme_gadgets", module_yml=gadgets))
    assert (
        r.status_code == 403 and "namespace acme belongs to another account" in r.json()["detail"]
    )
    mine = manifest(name="gadgets", id_="bob.module.gadgets")
    assert (
        up(
            c, tokens["bob"], *wheel(dist="bob-gadgets", pkg="acme_gadgets", module_yml=mine)
        ).status_code
        == 201
    )


def test_the_owner_chooses_maintainers_who_publish_versions(registry):
    c, tokens = registry
    db = c.app.state.nest.bindings.get("nest.db")
    up(c, tokens["ada"], *wheel())
    with pytest.raises(service.AccessError, match="owner chooses"):
        service.add_maintainer(
            db, "widgets", c.users["bob"], c.users["bob"].id
        )  # not bob's to grant
    assert up(c, tokens["bob"], *wheel(version="1.1.0")).status_code == 403
    service.add_maintainer(db, "widgets", c.users["ada"], c.users["bob"].id)
    assert up(c, tokens["bob"], *wheel(version="1.1.0")).status_code == 201  # a maintainer now
    assert "bob@example.org" in c.get("/p/widgets").text
    service.remove_maintainer(db, "widgets", c.users["ada"], c.users["bob"].id)
    assert up(c, tokens["bob"], *wheel(version="1.2.0")).status_code == 403


def test_a_disabled_account_publishes_nothing(registry):
    c, tokens = registry
    db = c.app.state.nest.bindings.get("nest.db")
    with db.engine().begin() as conn:
        conn.exec_driver_sql("update auth_user set active = 0 where email = 'ada@example.org'")
    assert up(c, tokens["ada"], *wheel()).status_code == 401


def test_who_may_not_publish_is_told_and_gets_no_token(tmp_path):
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"), "eve@example.org", "correct horse battery"
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "eve@example.org",
                "password": "correct horse battery",
            },
        )
        page = c.get("/tokens").text
        assert "administrators approve publishers" in page and 'action="/tokens"' not in page
        assert (
            c.post("/tokens", data={"csrf_token": c.cookies["nest_csrf"], "name": "x"}).status_code
            == 403
        )


# --- R2: what an application needs, found and checked ------------------------------------------


def host_wheel(version="0.2.0"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("nest/__init__.py", "")
        z.writestr(
            f"nest_core-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.3\nName: nest-core\nVersion: {version}\nSummary: The host.\n",
        )
    return f"nest_core-{version}-py3-none-any.whl", buf.getvalue()


def test_the_host_is_in_the_index_only_and_only_administrators_publish_it(registry):
    c, tokens = registry
    assert up(c, tokens["ada"], *host_wheel()).status_code == 403
    assert up(c, tokens["admin"], *host_wheel()).status_code == 201
    assert 'href="nest-core/"' in c.get("/simple/").text  # uv finds it
    assert c.get("/api/v1/packages").json()["packages"] == []  # no package to add
    bare = wheel(dist="acme-bare", pkg="acme_bare", module_yml=False)
    assert up(c, tokens["admin"], *bare).status_code == 400  # only the listed host


def test_the_newest_release_that_works_with_this_nest(registry):
    c, tokens = registry
    up(c, tokens["ada"], *wheel(version="1.0.0"))
    newer = manifest(version="2.0.0", nest='">=1.0,<2"')
    up(c, tokens["ada"], *wheel(version="2.0.0", module_yml=newer))
    assert c.get("/api/v1/packages").json()["packages"][0]["version"] == "2.0.0"
    fits = c.get("/api/v1/packages?nest=0.2.0").json()["packages"]
    assert fits[0]["version"] == "1.0.0" and fits[0]["nest"] == ">=0.2,<1"
    assert c.get("/api/v1/packages?nest=5.0").json()["packages"] == []


def test_a_package_page_tells_what_its_author_says_and_shows_a_theme(registry):
    c, tokens = registry
    told = (
        "# widgets — small widgets for pages.\n#\n# A second paragraph,\n# wrapped over lines.\n"
        + manifest()
    )
    up(c, tokens["ada"], *wheel(module_yml=told))
    page = c.get("/p/widgets").text
    assert "small widgets for pages." in page and "A second paragraph, wrapped over lines." in page
    theme = textwrap.dedent("""
        module: {name: dusk, id: acme.theme.dusk, type: theme, version: 1.0.0, title: Dusk}
        nest: ">=0.2,<1"
        main: acme_dusk
        screenshot: static/shot.png
        preview: {bg: "#101010", accent: "#ff8800"}
    """)
    buf = io.BytesIO()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("acme_dusk/__init__.py", "")
        z.writestr("acme_dusk/module.yml", theme)
        z.writestr("acme_dusk/static/shot.png", png)
        z.writestr(
            "acme_dusk-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: acme-dusk\nVersion: 1.0.0\n",
        )
    assert (
        up(c, tokens["ada"], "acme_dusk-1.0.0-py3-none-any.whl", buf.getvalue()).status_code == 201
    )
    assert "/p/dusk/screenshot" in c.get("/p/dusk").text
    shot = c.get("/p/dusk/screenshot")
    assert shot.content == png and shot.headers["content-type"] == "image/png"


def test_installing_from_the_registry_takes_its_nest_dependencies_from_it(
    registry, tmp_path, monkeypatch
):
    import nest.remote as remote  # noqa: PLC0415
    from nest.packages import add  # noqa: PLC0415

    c, tokens = registry
    gizmo = textwrap.dedent("""
        module: {name: gizmo, id: acme.module.gizmo, type: module, version: 1.0.0}
        nest: ">=0.2,<1"
        main: acme_gizmo
    """)
    up(c, tokens["ada"], *wheel(dist="acme-gizmo", pkg="acme_gizmo", module_yml=gizmo))
    needs = manifest().replace('deps: {auth: ">=0.3,<1"}', 'deps: {gizmo: ">=1.0,<2"}')
    up(c, tokens["ada"], *wheel(module_yml=needs))
    up(c, tokens["admin"], *host_wheel())
    assert c.get("/api/v1/packages/widgets").json()["deps"] == ["gizmo"]
    assert c.get("/api/v1/packages").json()["packages"][1]["dep_dists"] == ["acme-gizmo"]

    monkeypatch.setattr(remote, "_client", lambda url, token=None: _Same(c))
    monkeypatch.setenv("NEST_REGISTRY_URL", "https://registry.example.org")
    site = tmp_path / "site"
    site.mkdir()
    (site / "pyproject.toml").write_text(
        '[project]\nname = "site"\nversion = "0.1.0"\ndependencies = [\n    "nest-core>=0.2,<1",\n]\n',
        encoding="utf-8",
    )
    (site / "module.yml").write_text(
        "module: {name: site, id: test.app.site, type: application, version: 0.1.0}\n"
        "application: {title: Site, port: 8000, theme: base}\n",
        encoding="utf-8",
    )
    add(site, "widgets", remote=True, runner=lambda a, cwd: (0, ""), say=lambda _l: None)
    uv = tomllib.loads((site / "pyproject.toml").read_text())["tool"]["uv"]
    assert uv["sources"] == {"acme-widgets": {"index": "nest"}}
    # the index ahead of PyPI, not explicit: uv takes widgets' own Nest dependency (gizmo)
    # and nest-core from it too (the first index that has a package is the only one asked)
    assert uv["index"] == [{"name": "nest", "url": "https://registry.example.org/simple/"}]


def test_publish_all_publishes_what_the_registry_lacks(registry, tmp_path, monkeypatch):
    import nest.remote as remote  # noqa: PLC0415

    c, tokens = registry
    monkeypatch.setattr(remote, "_client", lambda url, token=None: _Same(c))
    monkeypatch.setenv("NEST_REGISTRY_TOKEN", tokens["admin"])
    sent = []
    monkeypatch.setattr(remote, "publish", lambda project, url, **kw: sent.append(project.name))
    roots = [REPO / "modules" / "forum", REPO / "modules" / "glossary"]
    up(
        c,
        tokens["admin"],
        *wheel(
            dist="nest-forum",
            pkg="nest_forum",
            module_yml=manifest(name="forum", id_="nest.module.forum", version="0.1.0"),
            version="0.1.0",
        ),
    )
    done, there, refused = remote.publish_all(roots, "https://registry.example.org")
    assert there == ["nest-forum 0.1.0"] and sent == ["glossary"] and not refused


def test_the_keeper_and_the_admin_panel_search_the_registry(registry, tmp_path, monkeypatch):
    import nest.remote as remote  # noqa: PLC0415

    c, tokens = registry
    up(c, tokens["ada"], *wheel())
    monkeypatch.setattr(remote, "_client", lambda url, token=None: _Same(c))
    from nest.packages import remote_offers  # noqa: PLC0415

    offers = remote_offers()
    assert offers["widgets"].dep_dists == [] and offers["widgets"].nest == ">=0.2,<1"


# --- R3: signatures, private packages, withdrawn versions ---------------------------------------


def _key():
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    from nest.signing import public_of  # noqa: PLC0415

    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return pem, public_of(pem)


def signed_up(c, token, name, data, pem, public, **extra):
    from nest.signing import sign  # noqa: PLC0415

    sha = hashlib.sha256(data).hexdigest()
    fields = {"signature": sign(pem, name, sha), "key": public, **extra}
    return c.post(
        "/api/v1/upload",
        files={"file": (name, data, "application/octet-stream")},
        data=fields,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_a_signature_counts_only_from_a_key_the_publisher_registered(registry):
    from nest.signing import fingerprint, verify  # noqa: PLC0415

    c, tokens = registry
    db = c.app.state.nest.bindings.get("nest.db")
    pem, public = _key()
    r = signed_up(c, tokens["ada"], *wheel(), pem, public)
    assert r.status_code == 400 and "has not registered" in r.json()["detail"]
    service.add_key(db, c.users["ada"].id, public, "laptop")
    other_pem, _ = _key()
    r = signed_up(c, tokens["ada"], *wheel(), other_pem, public)  # signed by another key
    assert r.status_code == 400 and "does not hold" in r.json()["detail"]
    name, data = wheel()
    assert signed_up(c, tokens["ada"], name, data, pem, public).status_code == 201
    f = c.get("/api/v1/packages/widgets").json()["files"][0]
    assert f["key"] == public and f["key_fingerprint"] == fingerprint(public)
    assert verify(public, name, f["sha256"], f["signature"])
    assert not verify(public, "other-name.whl", f["sha256"], f["signature"])  # bound to its name
    assert "✓ " + fingerprint(public) in c.get("/p/widgets").text


def test_a_registry_may_take_signed_files_only(registry):
    c, tokens = registry
    c.app.state.nest.settings.set("registry.require_signatures", True)
    r = up(c, tokens["ada"], *wheel())
    assert r.status_code == 400 and "signed files only" in r.json()["detail"]


def test_a_private_package_exists_for_its_people_only(registry):
    import base64  # noqa: PLC0415

    c, tokens = registry
    db = c.app.state.nest.bindings.get("nest.db")
    r = c.post(
        "/api/v1/upload",
        files={"file": wheel()},
        data={"visibility": "private"},
        headers={"Authorization": f"Bearer {tokens['ada']}"},
    )
    assert r.status_code == 201
    c.headers.clear()
    assert c.get("/api/v1/packages/widgets").status_code == 404  # like no package at all
    assert c.get("/simple/acme-widgets/").status_code == 404
    assert c.get("/api/v1/packages").json()["packages"] == []
    sha = r.json()["sha256"]
    assert c.get(f"/files/{sha}/{r.json()['file']}").status_code == 404
    as_uv = {
        "Authorization": "Basic " + base64.b64encode(f"__token__:{tokens['ada']}".encode()).decode()
    }
    assert c.get("/simple/acme-widgets/", headers=as_uv).status_code == 200  # uv, signed in
    as_bob = {"Authorization": f"Bearer {tokens['bob']}"}
    assert c.get("/api/v1/packages/widgets", headers=as_bob).status_code == 404
    service.add_maintainer(db, "widgets", c.users["ada"], c.users["bob"].id)
    assert c.get("/api/v1/packages/widgets", headers=as_bob).status_code == 200  # a maintainer sees
    r = c.post("/api/v1/packages/widgets/visibility", json={"visibility": "public"}, headers=as_bob)
    assert r.status_code == 403  # the owner chooses
    as_ada = {"Authorization": f"Bearer {tokens['ada']}"}
    assert (
        c.post(
            "/api/v1/packages/widgets/visibility", json={"visibility": "public"}, headers=as_ada
        ).status_code
        == 200
    )
    assert c.get("/api/v1/packages/widgets").status_code == 200


def test_a_withdrawn_version_is_passed_by_but_kept(registry):
    c, tokens = registry
    up(c, tokens["ada"], *wheel(version="1.0.0"))
    up(c, tokens["ada"], *wheel(version="1.1.0"))
    as_bob = {"Authorization": f"Bearer {tokens['bob']}"}
    assert (
        c.post(
            "/api/v1/packages/widgets/1.1.0/yank", json={"reason": "x"}, headers=as_bob
        ).status_code
        == 403
    )
    as_ada = {"Authorization": f"Bearer {tokens['ada']}"}
    r = c.post(
        "/api/v1/packages/widgets/1.1.0/yank", json={"reason": "breaks pages"}, headers=as_ada
    )
    assert r.status_code == 200
    assert (
        c.get("/api/v1/packages").json()["packages"][0]["version"] == "1.0.0"
    )  # newest unwithdrawn
    assert 'data-yanked="breaks pages"' in c.get("/simple/acme-widgets/").text
    js = c.get(
        "/simple/acme-widgets/", headers={"accept": "application/vnd.pypi.simple.v1+json"}
    ).json()
    assert {f["yanked"] for f in js["files"]} == {False, "breaks pages"}
    c.post("/api/v1/packages/widgets/1.1.0/yank", json={"undo": True}, headers=as_ada)
    assert c.get("/api/v1/packages").json()["packages"][0]["version"] == "1.1.0"


def test_the_installer_takes_only_what_a_trusted_key_signed(registry, tmp_path, monkeypatch):
    import nest.remote as remote  # noqa: PLC0415
    from nest.packages import PackageError, add  # noqa: PLC0415
    from nest.signing import trust  # noqa: PLC0415

    c, tokens = registry
    db = c.app.state.nest.bindings.get("nest.db")
    pem, public = _key()
    service.add_key(db, c.users["ada"].id, public, "laptop")
    signed_up(c, tokens["ada"], *wheel(), pem, public)
    monkeypatch.setattr(remote, "_client", lambda url, token=None: _Same(c))
    monkeypatch.setenv("NEST_REGISTRY_URL", "https://registry.example.org")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    site = tmp_path / "site"
    site.mkdir()
    (site / "pyproject.toml").write_text(
        '[project]\nname = "site"\nversion = "0.1.0"\ndependencies = [\n]\n', encoding="utf-8"
    )
    (site / "module.yml").write_text(
        "module: {name: site, id: test.app.site, type: application, version: 0.1.0}\n"
        "application: {title: Site, port: 8000, theme: base}\n",
        encoding="utf-8",
    )
    _, stranger = _key()
    trust("widgets", stranger)
    before = (site / "pyproject.toml").read_text()
    with pytest.raises(PackageError, match="a key widgets is not trusted with"):
        add(site, "widgets", remote=True, runner=lambda a, cwd: (0, ""), say=lambda _l: None)
    assert (site / "pyproject.toml").read_text() == before  # refused before anything changed
    trust("widgets", public)
    said = []
    add(site, "widgets", remote=True, runner=lambda a, cwd: (0, ""), say=said.append)
    assert any("is signed by" in line for line in said)


def test_a_signed_in_account_finds_its_tokens_in_the_menu(tmp_path):
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"),
            "ada@example.org",
            "correct horse battery",
            roles=("publisher",),
        )
        assert 'href="/tokens"' not in c.get("/").text  # nobody signed in
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ada@example.org",
                "password": "correct horse battery",
            },
        )
        assert 'href="/tokens"' in c.get("/").text
        page = c.get("/tokens").text
        assert "<title>Publish tokens · Nest packages</title>" in page  # nothing else in the title
        assert page.count("Signing keys") == 1 and page.count('action="/keys"') == 1


def test_a_new_token_comes_with_the_registrys_public_address(tmp_path):
    """Behind nginx the request may come to 127.0.0.1:8600: the command shown names the
    registry as the world reaches it (its public_url)."""
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        create_user(
            app.state.nest.bindings.get("nest.db"),
            "ada@example.org",
            "correct horse battery",
            roles=("publisher",),
        )
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "ada@example.org",
                "password": "correct horse battery",
            },
        )
        made = c.post(
            "/tokens",
            data={"csrf_token": c.cookies["nest_csrf"], "name": "laptop"},
            headers={"host": "127.0.0.1:8600"},
        )
        assert "nest login --registry https://registry.nest-framework.org --token nrt_" in made.text
        assert "127.0.0.1" not in made.text
