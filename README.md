# Nest

**Version 0.4.7** · [changelog](CHANGELOG.md) · licence [MIT](LICENSE) · documentation at [nest-framework.org](https://nest-framework.org/docs/)

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
(`packages/nest-core/src/nest/contracts/core.v1.yml`). An ecosystem can publish its own
contract to add types.

Every package keeps two files side by side at its root, for two purposes: `module.yml`, what
Nest knows it as (identity, what it gives and needs), and `pyproject.toml`, how Python builds
and installs it. Its code is in `src/<package>/`, and the manifest's paths (templates,
migrations, data) start there. An application folder has the same pair: its `module.yml`,
and a `pyproject.toml` that only gathers the Nest packages it runs on.

**How things look, in three layers**, each restyling the one before:

1. the theme (`themes/base/static/nest.css`): the tokens (`--bg`, `--surface`, `--accent`,
   `--font`, `--radius`...), the elements, and the classes modules share (`card`, `stack`,
   `row`, `field`, `notice`, `badge`, `tile`, `pager`);
2. each module's own stylesheet, its base look for its own markup, built only on those
   tokens: the manifest names it (`styles: [forum.css]`, in its `static/`), and every page of
   an application that includes the module loads it;
3. the application's own: its `styles:` (in its `static/`) load last, so it can change the
   tokens for every module at once or restyle one module's classes; its `templates/` override
   the theme's `layout.html` (its frame) or any one module's template.

So two sites can use the same forum, comments or sign-in, each in its own look, without
forking them.

An application in a repository of its own states what it needs of Nest in its `deps`, by
ecosystem and with versions, as RoboHub's manifests do:

```yaml
deps:
  nest:                  # Nest's own modules, providers and theme
    auth: ">=0.3,<1"
    db-sqlite: ">=0.1,<1"
  example:               # another ecosystem's packages, by its own name
    engine: ">=0.1,<1"
    part: ">=0.1,<1"
```

A module may be the host of parts: an engine and its subsystems, a module and its
extensions. The host declares what it takes and what comes with it; each part is a package of
its own, with its identity, that names its host and depends on it, so a part made later, in
another repository, joins the host the same way:

```yaml
# the host (engine/module.yml)
subsystems:
  types: [part]
  bundled: [one, two, ...]
# a part (parts/one/module.yml)
part_of: engine
deps: {example: {engine: ">=0.1,<1"}}
```

The plan refuses a part whose host the application does not include, a host that takes no
parts or not of that type, and a part that does not depend on its host.

Once an application declares deps, the plan holds it to them: each package it uses (the
modules it mounts, its theme, the interfaces it binds and their providers) must be listed,
under the ecosystem it belongs to (the one that defines its type, or names it in its id), at
a version installed; its own local modules need not be. Its `pyproject.toml` asks for the
same versions.

## Running

```sh
uv sync                                   # Python 3.13 and every workspace package
uv run nest plan applications/hello       # what the application is made of, in start order
uv run nest run applications/hello        # http://127.0.0.1:8100  (--reload while developing)
uv run nest serve applications/hello      # production: gunicorn's master and workers (docs/deploy.md)
uv run nest modules applications/hello    # its modules: core, enabled, disabled (docs/modules.md)
uv run nest packages ../mysite add forum  # install a trusted package (then enable it)
uv run nest themes ../mysite use paper    # the site's look (docs/themes.md)
uv run nest publish modules/forum         # to the Nest registry (docs/registry.md)
uv run nest validate --strict modules     # manifests, and the code keeping to them
uv run pytest                             # the tests
uv run nest validate .                    # every manifest against its contract
uv run nest new app myapp --into applications
uv run nest new module notes --into modules
```

## Where things live

```
packages/nest-core/   the host: manifests, contracts, catalog, resolution, bindings, security, SSE, CLI
modules/              reusable modules (htmx, auth, keys, forms, content, media, gallery, maps, geo, comments, rating, redirects, forum, messages, docs, seo, translations, notifications, push, pwa, consent, admin, agent, scheduler, keeper, registry)
interfaces/           interfaces (cache, db, pubsub, search, storage)
providers/            providers (cache-memory, redis, db-sqlite, db-postgres, db-mariadb, search-sqlite, storage-local)
themes/               themes (base, paper, slate)
applications/         Nest's own applications (keeper, hello, registry, docsite); the sites live in repos of their own beside it
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
| `NEST_ALLOWED_HOSTS` | the hosts it answers, comma-separated; any other gets 400 |
| `NEST_TRUSTED_PROXIES` | the proxies whose `X-Forwarded-*` headers `nest run` and `nest serve` believe |
| `NEST_WORKERS`, `NEST_THREADS` | `nest serve`'s processes and each one's threads (or the manifest's `serve:`) |
| `NEST_ROLE`, `NEST_ENGINE_URL` | set by `nest serve` for an application with an engine of its own: the engine process, the workers, where they reach it |

Running one for real (the image, `nest check`, `nest backup`/`restore`, Caddy in front)
is in [docs/deploy.md](docs/deploy.md).

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
# applications/mysite/module.yml: today
bind:
  nest.db: {providers: [db-sqlite]}
```

```yaml
# later: the same application on the dedicated server
bind:
  nest.db:
    providers: [db-postgres]
    config:
      db-postgres: {host: db.lan, database: mysite, user: mysite, sslmode: require}
```

The password comes from the environment, as `NEST_MYSITE__DB_POSTGRES__PASSWORD`.
A single secret URL works too, as `NEST_MYSITE__DB_POSTGRES__URL=postgresql://…`.

In a module:

```python
from nest_db import Database, model_base
from nest import bound

Base = model_base("notes")  # tables must be named notes_*


class Note(Base):
    __tablename__ = "notes_note"
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
  metadata: nest_notes.models:Base     # for --autogenerate
```

Each module keeps its own version table (`notes_alembic_version`) and migrates independently,
in dependency order. Autogenerate sees only tables under the module's prefix, so it can never
drop another module's tables. On SQLite, column changes are written as batch operations.

```sh
uv run nest db status applications/mysite
uv run nest db revision applications/mysite notes -m "add tags" --autogenerate
uv run nest db upgrade applications/mysite
uv run nest db downgrade applications/mysite notes -1
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
        return render(request, "notes/edit.html", form=form, fragment="form")
    ...
```

```jinja
{% import "forms/fields.html" as f %}
{{ f.field(form, "word", _("Word"), required=True, hint=_("As it is written")) }}
{{ f.field(form, "definition", _("Definition"), type="textarea") }}
```

The macros render labels, hints and errors, linked with `aria-invalid` and `aria-describedby`.

## Search

`nest.search` is an interface. Modules index documents and ask for matches, and the provider
decides how. `search-sqlite` keeps an FTS5 index in the workspace:

* diacritics are folded both ways, so "stiinta" finds "știință" and "ştiinţă" finds both;
* the last word typed matches as a prefix;
* titles rank above bodies;
* snippets are escaped first and then marked.

Whatever someone types is only words, never query syntax. The index is derived data, so a
module can always rebuild it from its records.

## Content: the CMS, and WordPress sites moved in

`content` is the CMS. It combines Geticus's content types with WordPress's posts, pages and
taxonomies.

* **Content types and taxonomies** are YAML (`content_types:`, `taxonomies:`). Any package can
  declare them, and the application's own declarations win. `content` declares WordPress's
  `post` and `page` with `category` and `post_tag`.
* **Custom fields** are typed (text, textarea, html, integer, decimal, boolean, date, datetime,
  select, url, media, entry). Each entry stores its fields as JSON, checked by a model built
  from the declarations, so there is no column per field.
* **Addresses** come from the type's path template (`/{category}/{slug}/`, `/{path}/`,
  `/evenimente/{year}/{slug}/`) and are stored. A page is found by its path when no route
  matches, so a moved site keeps every URL. Children follow their parent's slug.
* **Bodies** are HTML, sanitized with nh3 on every save. Shortcodes (`[catlist]`, `[gallery]`)
  are expanded only when shown, and only in text.
* **Also included:** media in `nest.storage` (served by the `media` module), menus, revisions,
  search, and an editor under `/admin/content` for the `editor` role.

```yaml
content_types:
  event:
    title: Evenimente
    path: "/evenimente/{year}/{slug}/"
    taxonomies: [category]
    fields:
      starts: {type: datetime, label: Începe, required: true}
      kind:   {type: select, choices: [hram, nedeie]}
```

A WordPress site moves in from its mysqldump and uploads folder. No MySQL server is needed:
`nest_db.mysqldump` reads the dump as data.

```sh
uv run nest content import-wordpress ../mysite ~/old-site/db/wordpress.sql \
    --uploads ~/old-site/wp-content/uploads
```

What the importer brings over:

* **Taxonomies, posts and pages:** categories and tags with their parents; posts and pages with
  their slugs, so the addresses stay the same.
* **Media:** featured images; attachments with their resized copies, and any other uploads the
  bodies link to.
* **Site structure:** menus and the static front page. Old `?p=123` links redirect.
* **Body cleanup:** WordPress's paragraphs are added once. Upload addresses on any host the site
  ever had become `/media/uploads/...`, and links to the old site become relative.

A Geticus site's pages move in the same way, with
`nest content import-geticus APP dump.sql --root SITE-FOLDER`. It brings categories, entries
(each type's rich-text field as the body, with its images copied over), the menu in the site's
language and the home page.

It is safe to run again: what it brought before is updated, not duplicated. The gallery plugins
come in through the `gallery` module, comments through `comments` (both below).

## Galleries, media and shortcodes: modules any application reuses

Features many sites need are modules of their own, as in RoboHub. An application includes them
at a route; they share nothing but the core's interfaces.

* **`media`** serves the files in `nest.storage` at its route (`/media` by convention, which
  imported pages assume). A stored HTML or SVG file is sent as a sandboxed attachment, never
  shown as a page. Templates get `media_url(key)`.
* **`gallery`** holds galleries of photos; an album is a gallery of galleries. Each has its own
  page under the module's route. Thumbnails open in a lightbox (one static script, CSP-safe);
  without JavaScript they are links.
* **Shortcodes** are a per-application registry in the core. A module answers a tag with
  `host.shortcode("album", fn)`, and a module that renders rich text expands them. So `gallery`
  gives `content`'s pages `[gallery slug="…"]` and `[album slug="…"]` without either importing
  the other. Shortcodes are expanded only in text, a tag nobody answers stays as written, and a
  failing handler renders nothing.

```sh
uv run nest gallery import-wordpress ../mysite ~/old-site/db/wordpress.sql \
    --uploads ~/old-site/wp-content/uploads        # --all for galleries no page uses
uv run nest gallery list ../mysite
```

The import moves Photo Gallery (10Web) and NextGEN galleries and albums with their photos and
thumbnails. It keeps the plugins' ids as aliases: `[Best_Wordpress_Gallery id="2"]` and
`[nggallery id=1]` in imported pages keep working, unchanged.

## Comments and redirects

**`comments`** works on anything. A page embeds a thread with
`{% if comments is defined %}{{ comments("content.entry:" ~ entry.id) }}{% endif %}`. The
subject is a name, not a foreign key, so any module's records can be commented without the
comments module knowing them.

* **Integrity:** the form carries the subject signed, so nobody can post to one a page did not
  offer.
* **Bodies:** plain text, shown with paragraphs and `nofollow ugc` links.
* **Guests:** when allowed, they wait for a moderator (the `moderator` role, at
  `<route>/moderate`). Members are published at once.
* **Robots:** they meet a honeypot, a minimum time, and a per-address limit. The address is kept
  only as a keyed hash.
* **Import:** `nest comments import-wordpress APP dump.sql` attaches WordPress comments to the
  pages their posts became. It finds them through the application's `wordpress.post` lookup,
  which `content` answers.

**`redirects`** sends old addresses on to new ones. It answers only after every page, so a page
that exists always wins over a redirect.

* **Targets:** a path on this site or an http(s) address. A loop is refused when it is added, and
  410 says a page is gone for good.
* **Tools:** editors work at the module's route (`/admin/redirects`); hit counts show which old
  links are still used; `nest redirects add | import-csv | list`.

Two core registries let modules cooperate without importing each other:

* **Lookups:** `host.answer("wordpress.post", fn)` and `nest.lookup(name, key)`.
* **Fallbacks:** answered by `priority`. `content` uses 10, `redirects` -10.

## Forum and messages: community, delivered live

**`forum`** has boards, topics and posts.

* **Access:** reading is public unless `public_read` is off. Posting is for members, at most
  `posts_per_minute`.
* **Editing:** authors edit for `edit_minutes`. Moderators pin, lock and hide.
* **Live replies:** a new reply is pushed over SSE (the topic family `forum.topic.*`) to everyone
  reading the topic, so it appears without a reload. Without JavaScript the form posts and the
  page reloads at the new post.

**`messages`** holds private conversations between members.

* **Privacy:** members write by email, or by name when it is unambiguous. Only participants see a
  conversation; anyone else gets a 404.
* **Live delivery:** each member has a channel, `messages.user.<id>`, that only they may follow. A
  new message appears in their open conversation, rendered for them, and their inbox refreshes.
  `{% include "messages/badge.html" %}` shows the unread count.

```sh
uv run nest forum add-board applications/hello "Discuții generale" --description "Orice despre Nest."
```

Realtime topics can be families (`forum.topic.*`). A family's
`authorize(request, name)` sees the concrete name, which is how a member may follow
`messages.user.7` only when they are member 7.

## The admin panel

Every application has one admin panel, made of what the application is made of. The `admin`
module is the shell, included once at a route (`/admin`). Each module gives it its own pages,
with `host.admin(router)`, and says in its manifest how they are listed:

```yaml
# a module's module.yml
admin: {title: Content, order: 10, role: editor, description: Pages, articles and menus.}
```

The panel mounts each module's pages at `<admin route>/<module>`: `/admin/content`,
`/admin/redirects`, `/admin/forum`. It shows each user a menu and a front page with only the pages
their roles open (the `admin` role opens all). A module's admin templates extend
`admin/layout.html`, and links come from `admin_url(request, module, path)`.

So two sites made of the same modules have the same panel. No panel is written for an
application, and an application without the admin module serves no admin pages (it says so at
start). A module whose pages are all in the panel needs no route of its own (redirects).

## The keeper

`applications/keeper` is Nest's own application, at port 8000. It orchestrates the applications
and covers what is generic to them. What is specific to one application is in that application's
admin panel. The keeper finds applications in two ways:

* installed packages of type application;
* the folders of its `apps` setting (`applications` by default): a folder of applications, or
  a folder that is one application, as each site's repository is. The keeper application
  lists Nest's own (`applications`: the keeper and hello) and the sites in repositories of their
  own beside Nest (`../mysite`).

For each application it shows the manifest, the plan (start order, routes, bindings, notes), any
problems, and whether it answers its health check on its port. That check runs on this machine
only, with a 0.3 s timeout. It also lists every package Nest can see, by type. Its pages are its
admin panel's, for the admin role.

```sh
uv run nest run applications/keeper          # http://127.0.0.1:8000 → /admin/keeper/
```

**The keeper's REST API** tells another orchestrator what Nest is and holds. It is read-only and
versioned, at `<keeper route>/api/v1`:

| Call | Answer |
|---|---|
| `GET /api/v1/ecosystem` | Nest itself: name, kind (web), version, the package types it knows |
| `GET /api/v1/apps` | every application: version, port, whether it runs, its problems |
| `GET /api/v1/apps/{name}` | one application: its plan (start order, routes, bindings, notes) |
| `GET /api/v1/packages` | every package Nest can see, by type |

* **Tokens:** every call carries `Authorization: Bearer nk_…`. A token is made in the keeper's
  admin panel (API tokens) or with `nest keeper token APP NAME`. It is shown once and kept only
  as a SHA-256 hash, and it can be revoked (`nest keeper revoke`).
* **No cookies:** they are not read, so a signed-in browser cannot be made to call the API.
* **Throttling:** an address sending bad tokens again and again is answered 429 for a minute.
* **No caching:** answers are marked not to be cached.

## Safe by default

Responses over 1 KB are gzipped; the railway map's 292 KB travel as 50 KB. Every response
also gets a strict Content-Security-Policy (no inline script, no eval),
`X-Frame-Options: DENY`, `nosniff` and a same-origin referrer. Every unsafe request to a
module's routes needs a signed CSRF token: htmx sends it as a header from `<body hx-headers>`,
and plain forms send `{{ csrf_field }}`. The Origin header is checked too.

Other safety rules:

* An SSE topic can only be followed if a module registered it, either as public or with an
  `authorize` check.
* A module that uses a host facility it did not declare fails at startup.
* A required module that fails to set up stops the start; nothing is swallowed.
