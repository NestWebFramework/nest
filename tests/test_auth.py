"""The auth module, end to end, in an application with a protected module."""

import re
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.passwords import hash_password, needs_rehash, verify_password
from nest_auth.web import safe_next

from nest import create_app

FILES = {
    "module.yml": """
        module: {name: site, id: test.app.site, type: application, version: 0.1.0}
        application: {title: Site, port: 8000, theme: base}
        modules:
          - {name: auth, route: /auth}
          - {name: private, route: /private}
        bind:
          nest.db: {providers: [db-sqlite]}
    """,
    "modules/private/module.yml": """
        module: {name: private, id: test.module.private, type: module, version: 0.1.0}
        main: private
        deps: {auth: ">=0.1"}
    """,
    "modules/private/private/__init__.py": """
        from fastapi import APIRouter, Depends, Request
        from nest import ModuleHost, render
        from nest_auth import CurrentUser, require_role, require_user

        router = APIRouter()

        @router.get("/")
        def page(request: Request, user: CurrentUser = Depends(require_user)):
            return render(request, "private/page.html")

        @router.get("/admin")
        def admin(user: CurrentUser = Depends(require_role("admin"))):
            return {"admin": user.email}

        def setup(host: ModuleHost) -> None:
            host.mount(router)
    """,
    "modules/private/templates/page.html": """
        {% extends "layout.html" %}
        {% block nav %}{% include "auth/status.html" %}{% endblock %}
        {% block content %}<p>secret for {{ user.label }}</p>{% endblock %}
    """,
}

PASSWORD = "correct horse battery"


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    for rel, body in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def client_for(root: Path, ws: Path, **env: str) -> TestClient:
    return TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(ws), **env}))


def token(c: TestClient) -> str:
    c.get("/healthz")
    return c.cookies["nest_csrf"]


def post(c: TestClient, url: str, **data: str):
    return c.post(url, data={"csrf_token": token(c), **data}, follow_redirects=False)


def register(c: TestClient, email: str = "ana@example.ro", password: str = PASSWORD):
    return post(c, "/auth/register", email=email, name="Ana", password=password)


def test_the_first_account_registers_and_administers(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        assert "This is the first account" in c.get("/auth/register").text
        r = register(c)
        assert r.status_code == 303 and r.headers["location"] == "/"
        cookie = r.headers["set-cookie"]
        assert "nest_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert c.get("/private/admin").json() == {"admin": "ana@example.ro"}
        page = c.get("/private/").text
        assert "secret for Ana" in page and "Sign out" in page


def test_registration_closes_after_the_first_account(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        register(c)
    with client_for(site, tmp_path / "ws") as other:
        assert other.get("/auth/register").status_code == 404
        assert register(other, "mihai@example.ro").status_code == 404


def test_registration_can_be_opened_and_new_accounts_are_not_admins(site, tmp_path):
    ws = tmp_path / "ws"
    with client_for(site, ws) as c:
        register(c)
    with client_for(site, ws, NEST_SITE__AUTH__ALLOW_REGISTRATION="true") as c:
        assert register(c, "mihai@example.ro").status_code == 303
        assert c.get("/private/").status_code == 200
        assert c.get("/private/admin").status_code == 403


def test_registration_refuses_weak_or_duplicate_accounts(site, tmp_path):
    with client_for(site, tmp_path / "ws", NEST_SITE__AUTH__ALLOW_REGISTRATION="1") as c:
        r = register(c, password="short")
        assert r.status_code == 400 and "at least 10 characters" in r.text
        assert register(c, "not-an-email").status_code == 400
        register(c)
        r = register(c, "ANA@example.ro")
        assert r.status_code == 400 and "already exists" in r.text


def test_anonymous_visitors_are_sent_to_sign_in_and_back(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        register(c)
    with client_for(site, tmp_path / "ws") as c:
        r = c.get("/private/?tab=1", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/auth/login?next=/private/%3Ftab%3D1"
        assert c.get("/private/admin", follow_redirects=False).status_code == 303
        r = post(
            c, "/auth/login", email="ana@example.ro", password=PASSWORD, next="/private/?tab=1"
        )
        assert r.status_code == 303 and r.headers["location"] == "/private/?tab=1"
        assert c.get("/private/").status_code == 200


def test_a_wrong_password_is_refused_and_repeated_failures_pause(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        register(c)
    with client_for(site, tmp_path / "ws") as c:
        for _ in range(5):
            r = post(c, "/auth/login", email="ana@example.ro", password="wrong password!")
            assert r.status_code == 401 and "Wrong email or password" in r.text
        r = post(c, "/auth/login", email="ana@example.ro", password=PASSWORD)
        assert r.status_code == 429 and "Too many attempts" in r.text
        r = post(c, "/auth/login", email="nobody@example.ro", password=PASSWORD)
        assert r.status_code == 401  # an unknown email reads like a wrong password


def test_htmx_sign_in_answers_a_fragment_or_a_redirect(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        register(c)
    with client_for(site, tmp_path / "ws") as c:
        headers = {"HX-Request": "true", "X-CSRF-Token": token(c)}
        r = c.post(
            "/auth/login", data={"email": "ana@example.ro", "password": "nope"}, headers=headers
        )
        assert r.status_code == 200 and r.text.lstrip().startswith('<form id="auth-form"')
        r = c.post(
            "/auth/login", data={"email": "ana@example.ro", "password": PASSWORD}, headers=headers
        )
        assert r.headers["hx-redirect"] == "/" and "nest_session=" in r.headers["set-cookie"]


def test_sign_out_ends_the_session_on_the_server(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c:
        register(c)
        stolen = c.cookies["nest_session"]
        assert post(c, "/auth/logout").status_code == 303
        assert c.get("/private/", follow_redirects=False).status_code == 303
    with client_for(site, tmp_path / "ws") as thief:
        thief.cookies.set("nest_session", stolen)
        assert thief.get("/private/", follow_redirects=False).status_code == 303


def test_the_session_token_is_not_stored(site, tmp_path):
    from sqlalchemy import text

    with client_for(site, tmp_path / "ws") as c:
        register(c)
        raw = c.cookies["nest_session"]
        db = c.app.state.nest.bindings.get("nest.db")
        with db.engine().connect() as conn:
            ids = [row[0] for row in conn.execute(text("SELECT id FROM auth_session"))]
            hashes = [row[0] for row in conn.execute(text("SELECT password_hash FROM auth_user"))]
    assert raw not in ids and len(ids[0]) == 64
    assert hashes[0].startswith("scrypt$") and PASSWORD not in hashes[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/private/", "/private/"),
        ("/a?b=c", "/a?b=c"),
        ("//evil.example/x", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("/x\r\nSet-Cookie: a=b", "/"),
        ("", "/"),
    ],
)
def test_next_goes_only_to_this_site(value, expected):
    assert safe_next(value) == expected


def test_passwords():
    stored = hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("other", stored)
    assert not verify_password(PASSWORD, "bcrypt$whatever") and not verify_password(
        PASSWORD, "junk"
    )
    assert not needs_rehash(stored) and needs_rehash("scrypt$1024$8$1$aa$bb")
    assert re.fullmatch(r"scrypt\$16384\$8\$1\$[\w-]+\$[\w-]+", stored)
    assert not verify_password("x" * 2000, stored)


def test_the_auth_command_creates_an_account(site, tmp_path, monkeypatch, capsys):
    import io

    from nest.cli import main

    monkeypatch.setenv("NEST_APP_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert (
        main(
            [
                "auth",
                "create-user",
                str(site),
                "ed@example.ro",
                "--role",
                "editor",
                "--password-stdin",
            ]
        )
        == 0
    )
    assert "ed@example.ro (roles: editor)" in capsys.readouterr().out
    with client_for(site, tmp_path / "ws") as c:
        assert post(c, "/auth/login", email="ed@example.ro", password=PASSWORD).status_code == 303
        assert c.get("/private/admin").status_code == 403


def test_a_member_keeps_their_own_account(site, tmp_path):
    with client_for(site, tmp_path / "ws") as c, client_for(site, tmp_path / "ws") as elsewhere:
        register(c)
        post(elsewhere, "/auth/login", email="ana@example.ro", password=PASSWORD)
        assert elsewhere.get("/private/").status_code == 200  # signed in on a second device
        page = c.get("/auth/account").text
        assert "ana@example.ro" in page and 'action="/auth/account/password"' in page
        assert (
            post(c, "/auth/account/name", name="Ana Popa").headers["location"]
            == "/auth/account?saved=name"
        )
        assert "secret for Ana Popa" in c.get("/private/").text
        wrong = post(
            c,
            "/auth/account/password",
            current="nope",
            new="a new long secret",
            again="a new long secret",
        )
        assert wrong.status_code == 400 and "current password is not right" in wrong.text
        differ = post(
            c, "/auth/account/password", current=PASSWORD, new="a new long secret", again="another"
        )
        assert differ.status_code == 400 and "differ" in differ.text
        done = post(
            c,
            "/auth/account/password",
            current=PASSWORD,
            new="a new long secret",
            again="a new long secret",
        )
        assert done.headers["location"] == "/auth/account?saved=password"
        assert c.get("/private/").status_code == 200  # here stays signed in
        assert elsewhere.get("/private/", follow_redirects=False).status_code in (
            302,
            303,
            307,
        )  # the other is out
        out = post(c, "/auth/account/sessions")
        assert out.status_code == 303 and c.get(
            "/private/", follow_redirects=False
        ).status_code in (302, 303, 307)
        assert post(c, "/auth/login", email="ana@example.ro", password=PASSWORD).status_code == 401
        assert (
            post(c, "/auth/login", email="ana@example.ro", password="a new long secret").status_code
            == 303
        )
