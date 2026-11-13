"""Forms: validation, messages in the visitor's language, accessible fields."""

import textwrap
from typing import Literal

from fastapi.testclient import TestClient
from nest_forms import Form, blank, validate
from pydantic import Field, field_validator
from starlette.datastructures import FormData

from nest import create_app
from nest.i18n import Translator


class TermForm(Form):
    word: str = Field(max_length=20)
    definition: str = Field(min_length=10)
    year: int | None = Field(default=None, ge=1000, le=2100)
    kind: Literal["noun", "verb"] = "noun"
    public: bool = False
    tags: list[str] = []

    @field_validator("word")
    @classmethod
    def no_digits(cls, v: str) -> str:
        if any(ch.isdigit() for ch in v):
            raise ValueError("A word has no digits.")
        return v


def test_a_valid_form_gives_typed_data():
    form = validate(
        TermForm,
        FormData(
            [
                ("word", "  voievod "),
                ("definition", "conducător al unui voievodat"),
                ("year", "1352"),
                ("public", "1"),
                ("tags", "istorie"),
                ("tags", "titlu"),
            ]
        ),
    )
    assert form.ok
    assert form.data.word == "voievod" and form.data.year == 1352
    assert form.data.public is True and form.data.tags == ["istorie", "titlu"]


def test_blank_means_not_given_and_every_field_reports_once():
    form = validate(
        TermForm, {"word": "   ", "definition": "short", "year": "abc", "kind": "adverb"}
    )
    assert not form.ok
    assert form.errors == {
        "word": "This field is required.",
        "definition": "Use at least 10 characters.",
        "year": "Enter a whole number.",
        "kind": "Choose one of the options.",
    }
    assert form.values["definition"] == "short"  # shown again as typed
    assert form.values["public"] is False  # an unticked box


def test_an_optional_blank_field_takes_its_default():
    form = validate(
        TermForm, {"word": "boier", "definition": "mare proprietar de pământ", "year": ""}
    )
    assert form.ok and form.data.year is None


def test_messages_are_translated_with_plural_forms(tmp_path):
    import json
    from pathlib import Path

    from nest_forms import __file__ as forms_init

    catalog = json.loads((Path(forms_init).parent / "locales" / "ro.json").read_text())
    t = Translator("ro", catalog)
    form = validate(TermForm, {"word": "x1", "definition": "scurt", "year": "900"}, t)
    assert form.errors["word"] == "A word has no digits."  # untranslated: falls back to English
    assert form.errors["definition"] == "Folosește cel puțin 10 caractere."
    assert form.errors["year"] == "Introdu 1000 sau mai mult."
    form = validate(TermForm, {"definition": "x" * 30, "word": "y" * 21}, t)
    assert form.errors["word"] == "Folosește cel mult 20 de caractere."


def test_blank_carries_initial_values():
    form = blank(TermForm, word="cneaz")
    assert form.values == {"word": "cneaz"} and form.errors == {} and not form.ok


APP = {
    "module.yml": """
        module: {name: words, id: test.app.words, type: application, version: 0.1.0}
        application: {port: 8000, theme: base, languages: [ro, en]}
        modules:
          - {name: terms, route: /terms}
    """,
    "modules/terms/module.yml": """
        module: {name: terms, id: test.module.terms, type: module, version: 0.1.0}
        main: terms
        deps: {forms: ">=0.1"}
    """,
    "modules/terms/terms/__init__.py": """
        from fastapi import APIRouter, Request
        from nest_forms import Form, blank, read
        from pydantic import Field
        from nest import ModuleHost, render

        class TermForm(Form):
            word: str = Field(max_length=20)
            definition: str = Field(min_length=10)

        router = APIRouter()

        @router.get("/new")
        def new(request: Request):
            return render(request, "terms/edit.html", form=blank(TermForm))

        @router.post("/new")
        async def create(request: Request):
            form = await read(request, TermForm)
            if not form.ok:
                return render(request, "terms/edit.html", form=form, fragment="form", status_code=200)
            return render(request, "terms/edit.html", form=form, fragment="form", saved=form.data.word)

        def setup(host: ModuleHost) -> None:
            host.mount(router)
    """,
    "modules/terms/templates/edit.html": """
        {% extends "layout.html" %}
        {% import "forms/fields.html" as f %}
        {% block content %}
        {% block form %}
        <form id="term" method="post" hx-post="/terms/new" hx-target="#term" hx-swap="outerHTML">
          {{ csrf_field }}
          {% if saved is defined %}<p class="notice ok">{{ saved }}</p>{% endif %}
          {{ f.field(form, "word", _("Word"), required=True, hint="Fără diacritice inutile") }}
          {{ f.field(form, "definition", _("Definition"), type="textarea", required=True) }}
          <button>OK</button>
        </form>
        {% endblock %}
        {% endblock %}
    """,
}


def test_a_form_page_round_trip(tmp_path):
    root = tmp_path / "words"
    for rel, body in APP.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        page = c.get("/terms/new").text
        assert (
            'id="f-word"' in page
            and 'aria-describedby="f-word-hint"' in page
            and "required" in page
        )
        token = c.cookies["nest_csrf"]
        headers = {"HX-Request": "true", "X-CSRF-Token": token}
        r = c.post(
            "/terms/new", data={"word": "<b>boier</b>", "definition": "scurt"}, headers=headers
        )
        assert r.text.lstrip().startswith('<form id="term"')
        assert 'aria-invalid="true"' in r.text and "Folosește cel puțin 10 caractere." in r.text
        assert "&lt;b&gt;boier&lt;/b&gt;" in r.text  # what was typed comes back escaped
        assert 'aria-describedby="f-definition-error"' in r.text
        r = c.post(
            "/terms/new",
            data={"word": "boier", "definition": "mare proprietar de pământ"},
            headers=headers,
        )
        assert '<p class="notice ok">boier</p>' in r.text
