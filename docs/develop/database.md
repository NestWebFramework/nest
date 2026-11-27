---
title: "Database, migrations and search"
description: "The nest.db interface and its providers, models per module, migrations with nest db, text tables for translated records, and the nest.search interface."
---

# Database, migrations and search

Modules never open a database themselves. They code against the `nest.db` interface
and SQLAlchemy sessions; the application binds the interface to an engine provider.
Moving a site from SQLite to PostgreSQL is a change of binding and settings, never of
module code.

## The pieces

| Package | Type | What it gives |
|---|---|---|
| `db` (`nest_db`) | interface `nest.db` | the `Database` protocol, `model_base`, the migration runner, `nest db`, text tables |
| `db-sqlite` | provider | SQLite in the workspace (`data/app.db`), WAL and foreign keys on |
| `db-postgres` | provider | PostgreSQL through a pool |
| `db-mariadb` | provider | MariaDB or MySQL through a pool |
| `search` (`nest_search`) | interface `nest.search` | the `Search` protocol, `Document`, `Hit`, `fold`, `highlight` |
| `search-sqlite` | provider | full-text search in SQLite (`data/search.db`) |

## Using the database in a module

Declare the interface and the dependency in `module.yml`:

```yaml
requires:
  interfaces: [nest.db]

deps:
  db: ">=0.2,<1"
```

Then reach the provider in `setup` with `host.bound("nest.db")`, or in a handler with the
`bound` dependency:

```python
from fastapi import APIRouter, Depends, Request
from nest_db import Database

from nest import bound, render

router = APIRouter()


@router.get("/")
def index(request: Request, q: str = "", db: Database = bound(Database)):
    return render(request, "redirects/index.html", redirects=service.listing(db, q.strip()))
```

The `Database` protocol:

| Method | Returns |
|---|---|
| `session()` | a new ORM session: `with db.session() as s, s.begin(): ...` |
| `engine()` | the SQLAlchemy engine, for Core queries |
| `dialect()` | `sqlite`, `postgresql` or `mariadb`, for the rare engine-specific path |
| `capabilities()` | what the engine offers beyond plain SQL (`json`, `fts`, `returning`, `schemas`) |
| `ping()` | whether the database answers now (the health page calls it) |
| `dispose()` | close every pooled connection (the host calls it at shutdown) |

Sessions are made with `expire_on_commit=False`, so records stay readable after the
transaction. Database calls block: a handler that queries is a plain `def`, which FastAPI
runs in its thread pool, or the work goes through `run_in_threadpool`.

## Models: one base per module

`model_base("content")` gives a declarative base whose tables must be named
`content_<name>`: two modules' tables can never collide in one database. Its metadata
names constraints by a fixed convention, so a migration written on SQLite drops the same
constraint on PostgreSQL.

```python
from nest_db import model_base
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

Base = model_base("content")


class Term(Base):
    """A category, a tag, or a term of any declared taxonomy."""

    __tablename__ = "content_term"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taxonomy: Mapped[str] = mapped_column(String(40), index=True)
    slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_term.id", ondelete="SET NULL"), nullable=True
    )
```

A class whose `__tablename__` lacks the prefix raises `TypeError` when it is defined.

## Binding a provider

The application binds the interface; the environment may switch providers it allows:

```yaml
bind:
  nest.db:
    providers: [db-sqlite]
    alternatives: [db-postgres]
```

```sh
NEST_BIND__NEST_DB=db-postgres
NEST_MYAPP__DB_POSTGRES__HOST=10.0.0.5
NEST_MYAPP__DB_POSTGRES__DATABASE=myapp
NEST_MYAPP__DB_POSTGRES__USER=myapp
NEST_MYAPP__DB_POSTGRES__PASSWORD=...
```

| Provider | Settings |
|---|---|
| `db-sqlite` | `path` (`data/app.db`, relative to the workspace), `journal_mode`, `synchronous`, `one_at_a_time`, `busy_timeout_ms` |
| `db-postgres` | `url` or `host`, `port`, `database`, `user`, `password`; `sslmode`, `pool_size`, `max_overflow`, `pool_timeout`, `statement_timeout_ms` |
| `db-mariadb` | `url` or `host`, `port`, `database`, `user`, `password`; `flavour`, `ssl_ca`, `pool_size`, `max_overflow`, `pool_recycle` |

`url` and `password` are secret: set in the environment only. See the reference pages of
[db-sqlite](/docs/reference/providers/db-sqlite), [db-postgres](/docs/reference/providers/db-postgres)
and [db-mariadb](/docs/reference/providers/db-mariadb).

## Migrations, per module

A module that owns tables says where its migrations are:

```yaml
db:
  migrations: migrations                    # a folder with versions/ inside
  metadata: "nest_content.models:Base"      # for --autogenerate
```

Each module migrates on its own, with its own version table
(`content_alembic_version`), in the order the plan starts modules, so a module's
migrations can rely on its dependencies' tables. Alembic sees only the module's own
tables (those with its prefix), and on SQLite alters tables in batch mode. Nest supplies
what Alembic's `env.py` would: a module has only its revision files.

```sh
uv run nest db status APP                       # each module: up to date or pending
uv run nest db upgrade APP [MODULE]             # apply what is pending
uv run nest db downgrade APP MODULE TARGET      # step a module back (a revision, or -1)
uv run nest db revision APP MODULE -m "who uploaded it" --autogenerate
```

`revision` creates the module's `migrations/versions/` and its `script.py.mako` the
first time. With `--autogenerate` it compares `db.metadata` with the database the
application is bound to; read what it wrote before keeping it. Nest's modules name their
revisions `<module>_0001`, `<module>_0002`, with `down_revision` pointing at the one
before.

When the application starts, `NEST_MIGRATE` decides:

| Value | Default when | Behaviour |
|---|---|---|
| `auto` | development | upgrade every module that is behind |
| `check` | production (`NEST_ENV=production`) | refuse to start while any module has migrations not applied: run `nest db upgrade` first |
| `off` | — | neither |

When an administrator uninstalls a module, the db interface's `forget` hook downgrades its
migrations to nothing and drops its version table.

### A new NOT NULL column

Rows already in the table need a value for a new column that cannot be NULL. Give it a
`server_default` in the migration. For a module `example` whose items gain a status:

```python
def upgrade() -> None:
    # existing items are published; no proposer
    with op.batch_alter_table("example_item", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="published")
        )
        batch_op.add_column(
            sa.Column("submitter_name", sa.String(length=200), nullable=False, server_default="")
        )
        batch_op.create_index(batch_op.f("ix_example_item_status"), ["status"], unique=False)
```

The model keeps its Python-side `default=`; the `server_default` fills the rows that were
there before.

## Text in every language: text tables

A record's text in the site's languages lives in a companion table, one row per record
per language, the default language included. What is the same in every language stays in
the record's own table.

```python
from nest_db import model_base, text_table
from sqlalchemy import String, Text
from sqlalchemy.orm import mapped_column

Base = model_base("content")

# ... Entry and Term as above ...

TermText = text_table(
    Base,
    Term,
    name=String(200),
    slug=String(200),
    path=mapped_column(String(500), nullable=True),
    description=Text,
    index=("path",),
)
```

`text_table(base, owner, *, unique=(), index=(), **fields)` makes `<owner table>_text`
with `owner_id` and `locale` (together its key), the given columns, a per-language
`status` (`published` or `draft`), `updated_at`, and `source_updated_at` (the default
language's `updated_at` the translation was made from). `unique` fields are unique within
a language (two languages may share a slug, one may not). Adding a language adds rows,
never columns.

| Helper (from `nest_db`) | Does |
|---|---|
| `save_text(session, model, owner_id, locale, values, *, status=None)` | writes the given fields; returns `(row, changed)`. `updated_at` moves only on a real change |
| `localize(session, model, ids, locale, default, *, fallback=True, drafts=False)` | the text of each id in `locale`, in one query; where it is missing, the default language's (`Localized.fallback` is then true) |
| `by_slug(session, model, locale, value, *, field="slug")` | the published row whose field is `value` in `locale`: an address |
| `text_rows(session, model, ids, locales=None)` | every text, as `{owner_id: {locale: row}}` |
| `delete_text(session, model, owner_id, locale)` | forgets one language's text |
| `text_state(row, source)` | `missing`, `draft`, `outdated` or `published` |

Saving a category's name in another language:

```python
def save_term_text(db, term_id: int, locale: str, name: str, description: str = ""):
    with db.session() as s, s.begin():
        save_text(
            s,
            TermText,
            term_id,
            locale,
            {"name": name.strip()[:200], "description": description.strip()},
        )
```

A module lists its text tables under `translatable:` in `module.yml`; the translations
module, when the application has it, then gives editors every language's fields, what is
missing or outdated, export and import. See [languages](../languages.md).

## Search

Declare `nest.search` in `requires.interfaces` and `search` in `deps`; the application
binds a provider (`search-sqlite`). Documents belong to a `kind` and have an id within
it:

```python
from nest_search import Document

search.index([
    Document(kind="content.entry", id=str(e.id), title=e.title, body=body, url=e.path, scope=e.type)
])
search.remove("content.entry", [str(e.id)])
hits = search.query(q, kind="content.entry", scope=entry_type or None, limit=20, offset=0)
```

| Method | Does |
|---|---|
| `index(documents)` | adds or replaces documents (by kind and id) |
| `remove(kind, ids)` | removes some |
| `clear(kind)` | forgets every document of a kind, before indexing it again |
| `query(text, *, kind, scope, limit, offset)` | matches for every word typed (the last as a prefix), best first, as `Hit`s |
| `count(text, *, kind, scope)` | how many match |
| `suggest(prefix, *, kind, scope, limit)` | titles starting with what was typed so far |

`scope` narrows a search (an entry type, a category) and is matched exactly. A `Hit` has
`title`, `url`, `snippet` and `snippet_html()`: the snippet escaped, its matches in
`<mark>`. `fold(text)` lowers case and drops diacritics ("Știință" → "stiinta"). Search
calls block, like database calls: search from a plain `def` handler.

Index on every save, and give the module a command to rebuild its part of the index
(the content module's `nest content reindex APP` clears its kind and indexes every entry).
