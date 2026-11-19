"""Translations: catalogs, plural forms, choosing a language, switching it."""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

from nest import create_app
from nest.i18n import Catalogs, I18nError, Translator

RO_PLURAL = {"{n} term": ["{n} termen", "{n} termeni", "{n} de termeni"]}


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (1, "1 termen"),
        (0, "0 termeni"),
        (2, "2 termeni"),
        (19, "19 termeni"),
        (20, "20 de termeni"),
        (101, "101 termeni"),
        (120, "120 de termeni"),
    ],
)
def test_romanian_has_three_plural_forms(n, text):
    assert Translator("ro", RO_PLURAL).ngettext("{n} term", "{n} terms", n) == text


def test_untranslated_text_falls_back_to_english():
    t = Translator("ro", {})
    assert t("Saved.") == "Saved."
    assert t.ngettext("{n} term", "{n} terms", 3) == "3 terms"
    assert t("Hello {name}", name="Ana") == "Hello Ana"
    assert t("Hello {name}") == "Hello {name}"  # a missing value never breaks a page


@pytest.mark.parametrize(
    ("chosen", "accept", "expected"),
    [
        (None, "ro-RO,ro;q=0.9,en;q=0.8", "ro"),
        (None, "en-GB,en;q=0.9", "en"),
        (None, "de,fr;q=0.5", "ro"),  # none offered: the default
        (None, "fr;q=0.2, en;q=0.9", "en"),
        ("en", "ro", "en"),  # a visitor's choice wins
        ("xx", "en", "en"),  # an unknown choice is ignored
        (None, None, "ro"),
    ],
)
def test_negotiation(chosen, accept, expected):
    assert Catalogs(["ro", "en"], "ro").negotiate(chosen, accept) == expected


def test_catalogs_are_checked(tmp_path):
    catalogs = Catalogs(["ro"], "ro")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(I18nError, match="not valid JSON"):
        catalogs.load("m", "ro", bad)
    bad.write_text(json.dumps({"a": 1}))
    with pytest.raises(I18nError, match="must map to text"):
        catalogs.load("m", "ro", bad)
    with pytest.raises(I18nError, match="listed but missing"):
        catalogs.load("m", "ro", tmp_path / "absent.json")
    with pytest.raises(I18nError, match="default language 'en' is not among"):
        Catalogs(["ro"], "en")


@pytest.fixture
def site(tmp_path):
    files = {
        "module.yml": """
            module: {name: site, id: test.app.site, type: application, version: 0.1.0}
            application:
              title: Dicționar
              port: 8000
              theme: base
              languages: [ro, en]
            modules:
              - {name: auth, route: /auth}
            bind:
              nest.db: {providers: [db-sqlite]}
            locales:
              - {locale: ro, file: locales/ro.json}
              - {locale: en, file: locales/en.json}
        """,
        # The application rewords the auth module: a text anywhere, and one in auth alone
        # ("auth::"), in Romanian and in English alike.
        "locales/ro.json": json.dumps(
            {"Sign in": "Intră în cont", "auth::Email": "Adresa ta"}, ensure_ascii=False
        ),
        "locales/en.json": json.dumps({"auth::Password": "Secret word"}),
    }
    root = tmp_path / "site"
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}))


def test_pages_speak_the_visitors_language(site):
    with site as c:
        ro = c.get("/auth/login").text
        assert '<html lang="ro">' in ro
        assert "Intră în cont" in ro and "Parolă" in ro  # the app's wording, the module's catalog
        en = c.get("/auth/login", headers={"Accept-Language": "en-US,en"}).text
        assert '<html lang="en">' in en and "Secret word" in en and "Parolă" not in en


def test_messages_from_python_are_translated(site):
    with site as c:
        c.get("/healthz")
        token = c.cookies["nest_csrf"]
        r = c.post("/auth/login", data={"csrf_token": token, "email": "a@b.ro", "password": "x"})
        assert "Email sau parolă greșită." in r.text


def test_the_language_switch(site):
    with site as c:
        c.get("/healthz")
        token = c.cookies["nest_csrf"]
        assert c.post("/_nest/language", data={"language": "en"}).status_code == 403  # CSRF
        r = c.post(
            "/_nest/language",
            data={"csrf_token": token, "language": "en", "next": "/auth/login"},
            follow_redirects=False,
        )
        assert r.status_code == 303 and r.headers["location"] == "/auth/login"
        assert "nest_locale=en" in r.headers["set-cookie"]
        assert '<html lang="en">' in c.get("/auth/login").text
        r = c.post(
            "/_nest/language",
            data={"csrf_token": token, "language": "xx", "next": "https://evil.example"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/" and "set-cookie" not in r.headers
        page = c.get("/auth/login").text
        assert "/_nest/language?language=ro&amp;" in page and 'aria-current="true"' in page


def test_an_application_rewords_one_module_in_any_language(site):
    with site as c:
        ro = c.get("/auth/login").text
        assert "Adresa ta" in ro and ">Email<" not in ro  # auth's "Email", reworded for auth only
        en = c.get("/auth/login", headers={"Accept-Language": "en"}).text
        assert "Secret word" in en and ">Password<" not in en  # English is reworded the same way


def test_a_page_embedded_in_an_applications_screen_is_only_its_content(site):
    with site as c:
        r = c.get("/auth/login", headers={"X-Nest-Embed": "content"})
        assert r.status_code == 200 and "<html" not in r.text and 'id="auth-form"' in r.text
        assert "X-Nest-Embed" in r.headers["vary"]  # a cache keeps the page and the part apart
        assert "<html" in c.get("/auth/login").text  # without the header, the whole page
        assert c.get("/auth/login", headers={"X-Nest-Embed": "nowhere"}).status_code == 400
