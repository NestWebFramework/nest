"""A record's text in every language: the text table helper (nest_db) and the
translations module (editors' fields, states, the backlog, export and import).

The notes module here is written the way content will be: what is the same in every
language in its own table, its text in a text table (one row per language, the default
included), and the translations module plugged in through its manifest and lookups.
"""

import json
import textwrap
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from nest_db import by_slug, localize, model_base, save_text, text_rows, text_state, text_table
from sqlalchemy import String, Text, create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from test_admin_modules import register
from test_auth import post

from nest import create_app
from nest.boundaries import check
from nest.catalog import Catalog, Entry
from nest.manifest import load_manifest

# --- the helper ---------------------------------------------------------------------------------

Base = model_base("shop")


class Product(Base):
    __tablename__ = "shop_product"
    id: Mapped[int] = mapped_column(primary_key=True)
    price: Mapped[int] = mapped_column(default=0)


ProductText = text_table(
    Base, Product, name=String(200), slug=String(200), about=Text, unique=("slug",)
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([Product(id=1), Product(id=2)])
        s.flush()
        yield s


def test_a_text_table_is_one_row_per_language_never_a_column_per_language():
    columns = {c.name for c in ProductText.__table__.columns}
    assert columns == {
        "owner_id",
        "locale",
        "status",
        "updated_at",
        "source_updated_at",
        "name",
        "slug",
        "about",
    }
    assert (
        ProductText.__tablename__ == "shop_product_text" and Product.__text_model__ is ProductText
    )
    assert [c.name for c in ProductText.__table__.primary_key.columns] == ["owner_id", "locale"]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    indexes = {i["name"] for i in inspect(engine).get_indexes("shop_product_text")}
    assert "ix_shop_product_text_locale" in indexes
    with pytest.raises(TypeError, match="text table's own"):
        text_table(model_base("x"), Product, locale=String(5))


def test_a_listing_is_one_query_with_the_default_standing_in(session):
    save_text(session, ProductText, 1, "ro", {"name": "Brânză", "slug": "branza"})
    save_text(session, ProductText, 1, "en", {"name": "Cheese", "slug": "cheese"})
    save_text(session, ProductText, 2, "ro", {"name": "Țuică", "slug": "tuica"})
    save_text(
        session,
        ProductText,
        2,
        "en",
        {"name": "Plum brandy", "slug": "plum-brandy"},
        status="draft",
    )
    shown = localize(session, ProductText, [1, 2], "en", "ro")
    assert shown[1].name == "Cheese" and not shown[1].fallback
    assert shown[2].name == "Țuică" and shown[2].fallback  # the English one is a draft
    assert localize(session, ProductText, [1, 2], "en", "ro", drafts=True)[2].name == "Plum brandy"
    assert 2 not in localize(session, ProductText, [1, 2], "en", "ro", fallback=False)
    assert by_slug(session, ProductText, "en", "cheese").owner_id == 1
    assert by_slug(session, ProductText, "en", "plum-brandy") is None  # not published
    assert by_slug(session, ProductText, "hu", "cheese") is None
    # a new language is new rows, the table as it was
    save_text(session, ProductText, 1, "hu", {"name": "Sajt", "slug": "sajt"})
    assert set(text_rows(session, ProductText, [1])[1]) == {"ro", "en", "hu"}


def test_slugs_are_unique_within_a_language_only(session):
    save_text(session, ProductText, 1, "ro", {"slug": "pita"})
    save_text(session, ProductText, 1, "en", {"slug": "pita"})  # the same word, two languages
    session.flush()
    save_text(session, ProductText, 2, "en", {"slug": "pita"})
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_translation_is_outdated_only_by_a_real_change_to_its_source(session):
    source, _ = save_text(session, ProductText, 1, "ro", {"name": "Brânză"})
    made, _ = save_text(
        session, ProductText, 1, "en", {"name": "Cheese"}, source_updated_at=source.updated_at
    )
    assert text_state(made, source) == "published"
    _, changed = save_text(session, ProductText, 1, "ro", {"name": "Brânză"})  # saved, unchanged
    assert not changed and text_state(made, source) == "published"
    source.updated_at += timedelta(seconds=1)  # what a real edit does
    assert text_state(made, source) == "outdated"
    assert text_state(None, source) == "missing"


# --- the module ---------------------------------------------------------------------------------

APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base, languages: [ro, en], language_urls: prefix, browser_language: false}
modules:
  - {name: auth, route: /cont}
  - {name: admin, route: /admin}
  - {name: translations}
  - {name: notes, route: /notes}
bind:
  nest.db: {providers: [db-sqlite]}
"""

NOTES = {
    "modules/notes/module.yml": """
        module: {name: notes, id: test.module.notes, type: module, version: 0.1.0}
        main: notes
        requires: {interfaces: [nest.db]}
        deps: {db: ">=0.2"}
        uses: [translations]
        db: {migrations: migrations, metadata: "notes:Base"}
        translatable:
          note:
            model: "notes:NoteText"
            label: Notes
            fields: {title: text, slug: slug, body: html}
            clean: "notes:clean"
            edit: "/notes/edit/{id}"
    """,
    "modules/notes/migrations/versions/0001_notes.py": """
        \"\"\"notes

        Revision ID: notes_0001
        \"\"\"
        import sqlalchemy as sa
        from alembic import op

        revision = "notes_0001"
        down_revision = None
        branch_labels = None
        depends_on = None


        def upgrade():
            op.create_table("notes_note", sa.Column("id", sa.Integer(), primary_key=True))
            op.create_table(
                "notes_note_text",
                sa.Column("owner_id", sa.Integer(), sa.ForeignKey("notes_note.id", ondelete="CASCADE"), primary_key=True),
                sa.Column("locale", sa.String(16), primary_key=True),
                sa.Column("status", sa.String(16), nullable=False),
                sa.Column("updated_at", sa.DateTime(), nullable=False),
                sa.Column("source_updated_at", sa.DateTime(), nullable=True),
                sa.Column("title", sa.String(200), nullable=False),
                sa.Column("slug", sa.String(200), nullable=False),
                sa.Column("body", sa.Text(), nullable=False),
                sa.UniqueConstraint("locale", "slug", name="uq_notes_note_text_locale_slug"),
            )
            op.create_index("ix_notes_note_text_locale", "notes_note_text", ["locale"])


        def downgrade():
            op.drop_table("notes_note_text")
            op.drop_table("notes_note")
    """,
    "modules/notes/notes/__init__.py": """
        from fastapi import APIRouter, HTTPException, Request
        from fastapi.responses import HTMLResponse, PlainTextResponse
        from nest_db import by_slug, localize, model_base, save_text, text_table
        from sqlalchemy import String, Text
        from sqlalchemy.orm import Mapped, mapped_column

        from nest import ModuleHost, render

        Base = model_base("notes")


        class Note(Base):
            __tablename__ = "notes_note"
            id: Mapped[int] = mapped_column(primary_key=True)


        NoteText = text_table(Base, Note, title=String(200), slug=String(200), body=Text, unique=("slug",))


        def clean(markup):
            # the module's rich text made safe (here: no script, no on... attributes)
            import re
            markup = re.sub(r"(?is)<script.*?</script>", "", markup)
            return re.sub(r'(?i)\\s+on[a-z]+="[^"]*"', "", markup)


        def setup(host: ModuleHost) -> None:
            db = host.bound("nest.db")
            router = APIRouter()

            @router.get("/edit/{note_id}")
            def edit(request: Request, note_id: int):
                return render(request, "notes/edit.html", note_id=note_id)

            @router.post("/edit/{note_id}")
            async def save(request: Request, note_id: int):
                form = await request.form()
                ask = {"subject": "notes.note", "id": note_id, "form": form}
                problem = host.lookup("translations.check", ask)
                if problem:
                    return PlainTextResponse(problem, status_code=400)
                with db.session() as s, s.begin():
                    if s.get(Note, note_id) is None:
                        s.add(Note(id=note_id))
                        s.flush()
                    save_text(s, NoteText, note_id, host.default_language,
                              {"title": form["title"], "slug": form["slug"], "body": form.get("body", "")})
                host.lookup("translations.save", ask)
                return PlainTextResponse("saved")

            @router.get("/{slug}")
            def page(request: Request, slug: str):
                locale, default = request.state.locale, host.default_language
                with db.session() as s:
                    row = by_slug(s, NoteText, locale, slug) or by_slug(s, NoteText, default, slug)
                    if row is None:
                        raise HTTPException(404)
                    t = localize(s, NoteText, [row.owner_id], locale, default)[row.owner_id]
                    note = " (not yet translated)" if t.fallback else ""
                    return HTMLResponse(f"<html><head></head><body><h1>{t.title}</h1>{note}</body></html>")

            host.mount(router)
    """,
    "modules/notes/templates/edit.html": """
        <form method="post">{{ csrf_field }}<input name="title"><input name="slug">
        {{ translation_fields("notes.note", note_id) }}</form>
    """,
}


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    files = {"module.yml": APP, **NOTES}
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


@pytest.fixture
def c(site, tmp_path):
    client = TestClient(
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}),
        follow_redirects=False,
    )
    with client:
        register(client)
        yield client


def write(c, note_id, **form):
    return post(c, f"/notes/edit/{note_id}", **form)


def test_a_module_edits_every_language_in_its_own_form(c):
    assert write(c, 1, title="Hora", slug="hora", body="<p>Joc</p>").text == "saved"
    form = c.get("/notes/edit/1").text
    assert (
        'name="tr_en_title"' in form and 'name="tr_ro_title"' not in form
    )  # the default is the module's own
    assert "Hora" in form  # the original beside the empty English field
    r = write(
        c,
        1,
        title="Hora",
        slug="hora",
        tr_en_present="1",
        tr_en_title="The hora",
        tr_en_slug="the-hora",
        tr_en_status="published",
    )
    assert r.text == "saved"
    assert "<h1>The hora</h1>" in c.get("/en/notes/the-hora").text
    assert "<h1>Hora</h1>" in c.get("/notes/hora").text
    # a page without an English text stands in Romanian, at its English address
    write(c, 2, title="Sârba", slug="sarba")
    assert "Sârba</h1> (not yet translated)" in c.get("/en/notes/sarba").text


def test_a_slug_taken_in_that_language_is_refused(c):
    write(
        c,
        1,
        title="Hora",
        slug="hora",
        tr_en_present="1",
        tr_en_title="Hora",
        tr_en_slug="hora-dance",
    )
    r = write(
        c,
        2,
        title="Sârba",
        slug="sarba",
        tr_en_present="1",
        tr_en_title="Sarba",
        tr_en_slug="hora-dance",
    )
    assert r.status_code == 400 and "hora-dance" in r.text
    r = write(
        c, 2, title="Sârba", slug="sarba", tr_en_present="1", tr_en_title="Sarba", tr_en_slug="a b"
    )
    assert r.status_code == 400


def test_the_backlog_shows_what_is_missing_outdated_or_a_draft(c):
    write(
        c,
        1,
        title="Hora",
        slug="hora",
        tr_en_present="1",
        tr_en_title="The hora",
        tr_en_slug="the-hora",
    )
    write(c, 2, title="Sârba", slug="sarba")
    write(
        c,
        3,
        title="Brâul",
        slug="braul",
        tr_en_present="1",
        tr_en_title="The belt",
        tr_en_slug="belt",
        tr_en_status="draft",
    )
    page = c.get("/admin/translations/?lang=en&state=todo").text
    assert "Sârba" in page and "Brâul" in page and ">Hora<" not in page
    assert c.get("/admin/translations/?lang=en&state=published").text.count("notes.note/1?") == 1
    # the original changes: its English is outdated, until saved again or said to hold
    write(c, 1, title="Hora mare", slug="hora")
    assert "Hora mare" in c.get("/admin/translations/?lang=en&state=outdated").text
    states = c.app.state.nest.lookup(
        "translations.states", {"subject": "notes.note", "ids": [1, 2, 3]}
    )
    assert states == {1: {"en": "outdated"}, 2: {"en": "missing"}, 3: {"en": "draft"}}
    r = post(
        c,
        "/admin/translations/notes.note/1",
        lang="en",
        tr_en_present="1",
        tr_en_title="The hora",
        tr_en_slug="the-hora",
        tr_en_status="published",
        tr_en_current="1",
    )
    assert r.status_code == 303
    assert c.app.state.nest.lookup(
        "translations.states", {"subject": "notes.note", "ids": [1]}
    ) == {1: {"en": "published"}}


def test_the_editor_starts_from_the_original_and_empty_removes(c):
    write(c, 1, title="Hora", slug="hora", body="<p>Joc în cerc</p>")
    page = c.get("/admin/translations/notes.note/1?lang=en")
    assert (
        page.status_code == 200 and "Joc în cerc" in page.text and 'name="tr_en_body"' in page.text
    )
    copy = post(c, "/admin/translations/notes.note/1", lang="en", copy="1")
    assert 'value="Hora"' in copy.text  # filled from the original, not saved
    assert c.app.state.nest.lookup(
        "translations.states", {"subject": "notes.note", "ids": [1]}
    ) == {1: {"en": "missing"}}
    post(
        c,
        "/admin/translations/notes.note/1",
        lang="en",
        tr_en_present="1",
        tr_en_title="Hora",
        tr_en_slug="hora-en",
    )
    post(
        c,
        "/admin/translations/notes.note/1",
        lang="en",
        tr_en_present="1",
        tr_en_title="",
        tr_en_slug="",
        tr_en_body="",
    )
    assert c.app.state.nest.lookup(
        "translations.states", {"subject": "notes.note", "ids": [1]}
    ) == {1: {"en": "missing"}}
    assert c.get("/admin/translations/nothing.here/1").status_code == 404


def test_export_and_import_for_a_translator(c, tmp_path):
    write(c, 1, title="Hora", slug="hora", body="<p>Joc</p>")
    write(c, 2, title="Sârba", slug="sarba")
    r = c.get("/admin/translations/export?lang=en&only=todo")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["format"] == "nest-translations/1" and data["locale"] == "en"
    assert [i["source"]["title"] for i in data["items"]] == ["Hora", "Sârba"]
    for item in data["items"]:
        item["text"] = {
            "title": item["source"]["title"] + " (en)",
            "slug": item["source"]["slug"] + "-en",
            "body": "",
        }
        item["status"] = "published"
    # meanwhile, someone changes Sârba's original: its translation comes back outdated
    write(c, 2, title="Sârba nouă", slug="sarba")
    upload = json.dumps(data).encode()
    r = c.post(
        "/admin/translations/import",
        data={"csrf_token": c.cookies["nest_csrf"]},
        files={"file": ("en.json", upload, "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    states = c.app.state.nest.lookup(
        "translations.states", {"subject": "notes.note", "ids": [1, 2]}
    )
    assert states == {1: {"en": "published"}, 2: {"en": "outdated"}}
    assert "<h1>Hora (en)</h1>" in c.get("/en/notes/hora-en").text
    r = c.post(
        "/admin/translations/import",
        data={"csrf_token": c.cookies["nest_csrf"]},
        files={"file": ("x.json", b"{}", "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 303  # refused, with a message, nothing written


def test_the_command_line_exports_and_imports(site, tmp_path, capsys, monkeypatch):
    from nest.cli import main

    monkeypatch.setenv("NEST_APP_WORKSPACE", str(tmp_path / "ws"))
    client = TestClient(create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}))
    with client:
        register(client)
        write(client, 1, title="Hora", slug="hora")
    out = tmp_path / "en.json"
    assert main(["translations", "export", str(site), str(out), "--lang", "en"]) == 0
    data = json.loads(out.read_text())
    data["items"][0]["text"] = {"title": "The hora", "slug": "the-hora"}
    out.write_text(json.dumps(data))
    assert main(["translations", "import", str(site), str(out)]) == 0
    assert main(["translations", "status", str(site)]) == 0
    assert "notes.note" in capsys.readouterr().out
    assert (
        main(["translations", "export", str(site), str(out), "--lang", "ro"]) == 1
    )  # the source itself


def test_a_declaration_that_does_not_hold_stops_the_start(site, tmp_path):
    manifest = site / "modules/notes/module.yml"
    manifest.write_text(manifest.read_text().replace('"notes:NoteText"', '"notes:Note"'))
    with pytest.raises(Exception, match="not a text table"):
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def test_a_module_translates_only_its_own_records(site):
    manifest = site / "modules/notes/module.yml"
    manifest.write_text(
        manifest.read_text().replace('"notes:NoteText"', '"nest_content.models:EntryText"')
    )
    notes = Entry(manifest=load_manifest(manifest), source="local")
    findings = check([notes], [*Catalog.discover(None), notes])
    assert any("a module translates its own records" in f.message for f in findings)


def test_rich_text_is_cleaned_by_its_module_however_it_comes_in(c):
    """A translation's html field is passed through the module's cleaner (translatable:
    clean:) from the form and from an imported file: never kept as it was sent."""
    write(c, 1, title="Hora", slug="hora", body="<p>Joc</p>")
    post(
        c,
        "/admin/translations/notes.note/1",
        lang="en",
        tr_en_present="1",
        tr_en_title="Hora",
        tr_en_slug="hora-en",
        tr_en_body='<p onclick="steal()">Round</p><script>steal()</script>',
    )
    from nest_db import text_rows

    kind = c.app.state.nest.module_state["translations"]["kinds"]["notes.note"]
    db = c.app.state.nest.bindings.get("nest.db")

    def body():
        with db.session() as s:
            return text_rows(s, kind.model, [1])[1]["en"].body

    assert body() == "<p>Round</p>"
    data = c.get("/admin/translations/export?lang=en&only=all").json()
    data["items"][0]["text"] = {
        "title": "Hora",
        "slug": "hora-en",
        "body": "<p>X</p><script>x()</script>",
    }
    c.post(
        "/admin/translations/import",
        data={"csrf_token": c.cookies["nest_csrf"]},
        files={"file": ("en.json", json.dumps(data).encode(), "application/json")},
    )
    assert body() == "<p>X</p>"


def test_an_html_field_without_a_cleaner_stops_the_start(site, tmp_path):
    manifest = site / "modules/notes/module.yml"
    manifest.write_text(manifest.read_text().replace('clean: "notes:clean"', ""))
    with pytest.raises(Exception, match="needs a cleaner"):
        create_app(site, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
