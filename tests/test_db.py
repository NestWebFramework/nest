"""The nest.db interface and its engine providers.

One module (notes) is written once against ``nest.db``. The same module runs on
SQLite here, and on PostgreSQL or MariaDB when a server is given:

    NEST_TEST_POSTGRES_URL=postgresql://nest:pw@127.0.0.1:5432/nest_test uv run pytest
    NEST_TEST_MARIADB_URL=mariadb://nest:pw@127.0.0.1:3306/nest_test uv run pytest

Only the application's ``bind:`` changes between the three.
"""

import os
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_db import model_base
from nest_db.server import ConfigError
from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nest import create_app
from nest.bind import BindError, ProviderContext, build_settings, conformance
from nest.catalog import Catalog

NOTES_MODULE = {
    "modules/notes/module.yml": """
        module:
          name: notes
          id: test.module.notes
          type: module
          version: 0.1.0
        main: notes
        requires:
          interfaces: [nest.db]
        deps:
          db: ">=0.1"
    """,
    "modules/notes/notes/__init__.py": """
        from fastapi import APIRouter, Form
        from nest_db import Database, model_base
        from sqlalchemy import String, select
        from sqlalchemy.orm import Mapped, mapped_column

        from nest import ModuleHost, bound

        Base = model_base("notes")


        class Note(Base):
            __tablename__ = "notes_note"
            id: Mapped[int] = mapped_column(primary_key=True)
            body: Mapped[str] = mapped_column(String(200))


        router = APIRouter()


        @router.post("/")
        def add(body: str = Form(), db: Database = bound(Database)):
            with db.session() as s, s.begin():
                s.add(Note(body=body))
            return {"ok": True}


        @router.get("/")
        def index(db: Database = bound(Database)):
            with db.session() as s:
                return {
                    "dialect": db.dialect(),
                    "notes": [n.body for n in s.scalars(select(Note).order_by(Note.id))],
                }


        def setup(host: ModuleHost) -> None:
            db = host.bound(Database)

            @host.on_startup
            def create_tables():  # until per-module migrations land
                Base.metadata.drop_all(db.engine())
                Base.metadata.create_all(db.engine())

            host.mount(router)
    """,
}


def notes_app(tmp_path: Path, bind: str) -> Path:
    root = tmp_path / "notes-app"
    files = {
        "module.yml": "module:\n  name: notes-app\n  id: test.app.notes\n  type: application\n"
        "  version: 0.1.0\napplication:\n  port: 8000\nmodules:\n  - name: notes\n    route: /notes\n"
        + textwrap.dedent(bind),
        **NOTES_MODULE,
    }
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def csrf(client: TestClient) -> str:
    client.get("/healthz")
    return client.cookies["nest_csrf"]


def exercise(app) -> str:
    with TestClient(app) as c:
        token = csrf(c)
        for body in ("întâi", "al doilea"):  # diacritics survive every engine
            assert c.post(
                "/notes/", data={"body": body}, headers={"X-CSRF-Token": token}
            ).json() == {"ok": True}
        listed = c.get("/notes/").json()
        assert listed["notes"] == ["întâi", "al doilea"]
        health = c.get("/_nest/health")
        assert health.status_code == 200 and all(health.json()["checks"].values())
        return listed["dialect"]


SQLITE = """
bind:
  nest.db:
    providers: [db-sqlite]
"""


def test_the_module_runs_on_sqlite(tmp_path):
    ws = tmp_path / "ws"
    app = create_app(notes_app(tmp_path, SQLITE), environ={"NEST_APP_WORKSPACE": str(ws)})
    assert exercise(app) == "sqlite"
    assert (ws / "data" / "app.db").is_file()


def test_sqlite_pragmas_are_applied(tmp_path):
    app = create_app(notes_app(tmp_path, SQLITE), environ={"NEST_APP_WORKSPACE": str(tmp_path)})
    db = app.state.nest.bindings.get("nest.db")
    with db.engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert "fts" in db.capabilities()


@pytest.mark.parametrize(
    ("variable", "provider", "dialect"),
    [
        ("NEST_TEST_POSTGRES_URL", "db-postgres", "postgresql"),
        ("NEST_TEST_MARIADB_URL", "db-mariadb", "mariadb"),
    ],
)
def test_the_same_module_runs_on_a_server(tmp_path, variable, provider, dialect):
    url = os.environ.get(variable)
    if not url:
        pytest.skip(f"set {variable} to run against a live server")
    bind = f"bind:\n  nest.db:\n    providers: [{provider}]\n"
    env_key = f"NEST_NOTES_APP__{provider.upper().replace('-', '_')}__URL"
    app = create_app(
        notes_app(tmp_path, bind), environ={"NEST_APP_WORKSPACE": str(tmp_path), env_key: url}
    )
    assert exercise(app) == dialect


def test_a_server_provider_without_settings_stops_the_start_clearly(tmp_path):
    bind = "bind:\n  nest.db:\n    providers: [db-postgres]\n"
    with pytest.raises(BindError) as e:
        create_app(notes_app(tmp_path, bind), environ={"NEST_APP_WORKSPACE": str(tmp_path)})
    assert "db-postgres could not start: set either url, or database and user" in str(e.value)
    assert "NEST_NOTES_APP__DB_POSTGRES__URL" in str(e.value)


def test_a_password_in_module_yml_is_refused(tmp_path):
    bind = """
    bind:
      nest.db:
        providers: [db-mariadb]
        config:
          db-mariadb: {database: x, user: u, password: hunter2}
    """
    with pytest.raises(BindError, match="db-mariadb.password is secret"):
        create_app(notes_app(tmp_path, bind), environ={"NEST_APP_WORKSPACE": str(tmp_path)})


def test_an_unknown_choice_is_refused(tmp_path):
    bind = """
    bind:
      nest.db:
        providers: [db-sqlite]
        config:
          db-sqlite: {journal_mode: "WAL; DROP TABLE x"}
    """
    with pytest.raises(BindError, match="db-sqlite.journal_mode"):
        create_app(notes_app(tmp_path, bind), environ={"NEST_APP_WORKSPACE": str(tmp_path)})


# --- the providers on their own --------------------------------------------------

CATALOG = Catalog.discover()
CTX = ProviderContext(app="glossary", workspace=Path("/srv/ws"))


def settings_for(provider: str, written: dict, environ: dict | None = None):
    specs = CATALOG.find(provider)[0].manifest.settings
    settings, problems = build_settings("glossary", provider, specs, written, environ or {})
    assert problems == []
    return settings


def test_postgres_url_from_parts_and_from_a_secret_url():
    import nest_db_postgres as pg

    s = settings_for(
        "db-postgres",
        {"host": "db.lan", "database": "glossary", "user": "web"},
        {"NEST_GLOSSARY__DB_POSTGRES__PASSWORD": "p@ss"},
    )
    url = pg.url_for(s, CTX)
    assert url.drivername == "postgresql+psycopg" and url.host == "db.lan" and url.port == 5432
    assert url.password == "p@ss" and url.query["sslmode"] == "prefer"
    assert "p@ss" not in url.render_as_string(hide_password=True)

    s = settings_for(
        "db-postgres", {}, {"NEST_GLOSSARY__DB_POSTGRES__URL": "postgres://a:b@h:6543/d"}
    )
    url = pg.url_for(s, CTX)
    assert (url.drivername, url.port, url.database) == ("postgresql+psycopg", 6543, "d")

    s = settings_for("db-postgres", {"statement_timeout_ms": 5000})
    assert pg.connect_args(s, CTX) == {
        "application_name": "glossary",
        "options": "-c timezone=UTC -c statement_timeout=5000",
    }


def test_mariadb_url_and_session_setup():
    import nest_db_mariadb as maria

    s = settings_for("db-mariadb", {"database": "dex", "user": "web", "flavour": "mysql"})
    url = maria.url_for(s, CTX)
    assert url.drivername == "mysql+pymysql" and url.port == 3306
    assert url.query["charset"] == "utf8mb4"
    args = maria.connect_args(s, CTX)
    assert (
        "time_zone='+00:00'" in args["init_command"]
        and "STRICT_TRANS_TABLES" in args["init_command"]
    )

    s = settings_for("db-mariadb", {}, {"NEST_GLOSSARY__DB_MARIADB__URL": "postgresql://a@h/d"})
    with pytest.raises(ConfigError, match="not one of mariadb, mysql"):
        maria.url_for(s, CTX)


def test_every_provider_keeps_the_interface(tmp_path):
    from nest_db import Database

    ctx = ProviderContext(app="t", workspace=tmp_path)
    for provider, written in [
        ("db-sqlite", {"path": ":memory:"}),
        ("db-postgres", {"database": "d", "user": "u"}),
        ("db-mariadb", {"database": "d", "user": "u"}),
    ]:
        module = __import__(provider.replace("-", "_").replace("db_", "nest_db_", 1))
        db = module.create(settings_for(provider, written), ctx)  # no connection is made
        assert conformance(Database, db, provider) == []
        db.dispose()


def test_model_base_keeps_tables_in_their_module():
    Base = model_base("glossary")

    class Term(Base):
        __tablename__ = "glossary_term"
        id: Mapped[int] = mapped_column(primary_key=True)
        word: Mapped[str] = mapped_column(String(80), unique=True)

    class Sense(Base):
        __tablename__ = "glossary_sense"
        id: Mapped[int] = mapped_column(primary_key=True)
        term_id: Mapped[int] = mapped_column(ForeignKey("glossary_term.id"))

    names = {c.name for c in Base.metadata.tables["glossary_term"].constraints if c.name}
    assert {"pk_glossary_term", "uq_glossary_term_word"} <= names
    fk = next(iter(Base.metadata.tables["glossary_sense"].foreign_key_constraints))
    assert fk.name == "fk_glossary_sense_term_id_glossary_term"

    with pytest.raises(TypeError, match="must be named 'glossary_…'"):

        class Stray(Base):
            __tablename__ = "terms"
            id: Mapped[int] = mapped_column(primary_key=True)
