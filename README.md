# Nest

A lightweight, manifest-driven host for web applications in Python: FastAPI,
server-rendered pages, htmx and Server-Sent Events, Vue only where a page
needs it. One application is one service on one port, made of reusable
modules that own no port. The design is in
[`../nest-framework-proposal.html`](../nest-framework-proposal.html).

## The words

| type | what it is |
|------|------------|
| `module` | Reusable code with a published API: routes, templates, settings. It owns no port; the application mounts it at a route. |
| `interface` | A named Protocol with no implementation (`nest.cache`). Code depends on it, never on a provider. |
| `provider` | Implements interfaces, with typed settings (`cache-memory`). |
| `theme` | Layouts, styles and blocks that modules fill. |
| `application` | Composes modules, binds each interface to providers, runs on one port with its own workspace. |

Each package is described by a `module.yml`, checked against the contract for its type
(`packages/nest-core/src/nest/contracts/core.v1.yml`). An ecosystem, such as the game,
can publish its own contract to add types.

## Running

```sh
uv sync                                   # Python 3.13 and every workspace package
uv run nest plan applications/hello       # what the application is made of, in start order
uv run nest run applications/hello        # http://127.0.0.1:8100  (--reload while developing)
uv run pytest                             # the tests
uv run nest validate .                    # every manifest against its contract
uv run nest new app myapp --into applications
uv run nest new module glossary --into modules
```

## Where things live

```
packages/nest-core/   the host: manifests, contracts, catalog, resolution, bindings, security, SSE, CLI
modules/              reusable modules (htmx, auth, forms)
interfaces/           interfaces (cache, db)
providers/            providers (cache-memory, db-sqlite, db-postgres, db-mariadb)
themes/               themes (base)
applications/         applications (hello)
```

At run time an application keeps its own files in its workspace,
`$NEST_APP_WORKSPACE` (default `~/.local/share/nest/<app>/`):
`.env` (secrets), `data/settings.conf` (runtime settings), `data/app.db` (SQLite), `media/`.

## Configuration

* **Build and deploy facts** go in `module.yml`.
* **Runtime settings** go in the settings store (`host.settings.get("per_page")`).
* **Secrets** come only from the environment. A secret written in `module.yml` stops the start.

Any declared setting can be overridden as `NEST_<APP>__<OWNER>__<KEY>`, for example
`NEST_HELLO__CACHE_MEMORY__MAX_ITEMS=500`.

| variable | meaning |
|----------|---------|
| `NEST_ENV` | `production` turns on secure cookies and HSTS, hides the API docs, and requires `NEST_SECRET_KEY` |
| `NEST_SECRET_KEY` | the signing key (32+ characters); generated into the workspace in development |
| `NEST_APP_WORKSPACE` | where the application keeps its data |
| `NEST_<APP>__DB_<ENGINE>__<KEY>` | a database provider's settings, e.g. `NEST_GLOSSARY__DB_POSTGRES__PASSWORD` |

## Databases

A database is an interface, `nest.db`, not part of the core. Modules code against the
`Database` protocol and SQLAlchemy sessions. The application binds the interface to one engine
provider, so changing databases means changing the binding. Module code stays the same.

| provider | engine | driver | for |
|----------|--------|--------|-----|
| `db-sqlite` | SQLite file in the workspace, WAL, foreign keys on | stdlib | local development, small sites |
| `db-postgres` | PostgreSQL, pooled, UTC, `sslmode`, statement timeout | psycopg 3 | the dedicated server |
| `db-mariadb` | MariaDB or MySQL, utf8mb4, strict SQL mode, UTC, pool recycle | PyMySQL (pure Python) | existing MariaDB/MySQL data |

```yaml
# applications/glossary/module.yml: today
bind:
  nest.db: {providers: [db-sqlite]}
```

```yaml
# later: the same application on the dedicated server
bind:
  nest.db:
    providers: [db-postgres]
    config:
      db-postgres: {host: db.lan, database: glossary, user: glossary, sslmode: require}
```

The password comes from the environment, as `NEST_GLOSSARY__DB_POSTGRES__PASSWORD`.
A single secret URL works too, as `NEST_GLOSSARY__DB_POSTGRES__URL=postgresql://…`.

In a module:

```python
from nest_db import Database, model_base
from nest import bound

Base = model_base("glossary")  # tables must be named glossary_*


class Term(Base):
    __tablename__ = "glossary_term"
    ...


@router.get("/")
def index(db: Database = bound(Database)):  # a sync handler runs in the threadpool
    with db.session() as s:
        ...
```

`model_base` gives every module a declarative base with a constraint naming convention.
That way a migration names the same constraints on SQLite, PostgreSQL and MariaDB.
`db.dialect()` and `db.capabilities()` (`json`, `fts`, `returning`, `schemas`) cover the
rare engine-specific path. The health page pings the database.

### Migrations, per module

A module that owns tables says where its migrations are. It ships only revision files,
because Nest supplies what Alembic's `env.py` would:

```yaml
db:
  migrations: migrations                  # migrations/versions/*.py
  metadata: nest_glossary.models:Base     # for --autogenerate
```

Each module keeps its own version table (`glossary_alembic_version`) and migrates independently,
in dependency order. Autogenerate sees only tables under the module's prefix, so it can never
drop another module's tables. On SQLite, column changes are written as batch operations.

```sh
uv run nest db status applications/glossary
uv run nest db revision applications/glossary glossary -m "add senses" --autogenerate
uv run nest db upgrade applications/glossary
uv run nest db downgrade applications/glossary glossary -1
```

At startup, `NEST_MIGRATE` decides what happens. `auto` is the default in development:
it upgrades. `check` is the default in production: it refuses to start while migrations are
pending. On microk8s, `nest db upgrade` runs as a Job before the Deployment rolls out.
`off` does neither.

To run the same tests against live servers:

```sh
NEST_TEST_POSTGRES_URL=postgresql://nest:pw@127.0.0.1:5432/nest_test uv run pytest
NEST_TEST_MARIADB_URL=mariadb://nest:pw@127.0.0.1:3306/nest_test uv run pytest
```

## Accounts

The `auth` module provides accounts with roles, sign-in and sign-out, and server-side sessions
on the bound database. Other modules protect their routes with a dependency:

```python
from nest_auth import CurrentUser, require_role, require_user


@router.get("/drafts")
def drafts(user: CurrentUser = Depends(require_user)): ...  # others are sent to sign in


@router.post("/terms/{id}/delete")
def delete(
    id: int, user: CurrentUser = Depends(require_role("editor"))
): ...  # admin has every role
```

How it works:

* Passwords are hashed with the standard library's scrypt.
* The browser holds a random token and the database stores only its SHA-256.
  Signing out ends the session on the server.
* Failed sign-ins are throttled per email and address.
* `?next=` only ever leads to a path on this site.
* An unknown email takes as long to refuse as a wrong password.
* Registration is closed unless `allow_registration` is set. The very first account can always
  register, and it becomes the administrator.
* Templates get `user`, plus `{% include "auth/status.html" %}` for the navigation.

```sh
uv run nest auth create-user applications/hello ana@example.ro --role admin
uv run nest auth sign-out-everywhere applications/hello ana@example.ro
```

## Languages

An application lists its languages: `application: {languages: [ro, en]}`. The first is the
default unless `default_language` says otherwise. Every package lists its JSON catalogs:

```yaml
locales:
  - {locale: ro, file: locales/ro.json}
```

A catalog maps the English text to its translation. A plural is a list with one form per plural
category, and Romanian has three:

```json
{"Wrong email or password.": "Email sau parolă greșită.",
 "{n} term": ["{n} termen", "{n} termeni", "{n} de termeni"]}
```

Templates use `{{ _("Sign in") }}` and `{{ ngettext("{n} term", "{n} terms", count) }}`.
In Python, use `translator(request)("Saved.")`.

The application's own catalogs are loaded last, so it can reword any module. A visitor's
language comes from their choice (`POST /_nest/language`, the base theme's switch), then
`Accept-Language`, then the default. `<html lang>` follows it.

## Forms

A form is a Pydantic model. `read()` validates the submitted fields and returns everything a
page needs: the values as typed, one translated message per field, or the typed data.
An empty field counts as not given, so a required field means "not blank".

```python
from nest_forms import Form, blank, read

class TermForm(Form):
    word: str = Field(max_length=80)
    definition: str = Field(min_length=10)

@router.post("/terms")
async def create(request: Request):
    form = await read(request, TermForm)
    if not form.ok:
        return render(request, "glossary/edit.html", form=form, fragment="form")
    ...
```

```jinja
{% import "forms/fields.html" as f %}
{{ f.field(form, "word", _("Word"), required=True, hint=_("As it is written")) }}
{{ f.field(form, "definition", _("Definition"), type="textarea") }}
```

The macros render labels, hints and errors, linked with `aria-invalid` and `aria-describedby`.

## Safe by default

Every response gets a strict Content-Security-Policy (no inline script, no eval),
`X-Frame-Options: DENY`, `nosniff` and a same-origin referrer. Every unsafe request to a
module's routes needs a signed CSRF token: htmx sends it as a header from `<body hx-headers>`,
and plain forms send `{{ csrf_field }}`. The Origin header is checked too.

Other safety rules:

* An SSE topic can only be followed if a module registered it, either as public or with an
  `authorize` check.
* A module that uses a host facility it did not declare fails at startup.
* A required module that fails to set up stops the start; nothing is swallowed.
