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
(`packages/nest-core/src/nest/contracts/core.v1.yml`). An ecosystem, such as the Saga
engine, can publish its own contract to add types.

Every package keeps two files side by side at its root, for two purposes: `module.yml`, what
Nest knows it as (identity, what it gives and needs), and `pyproject.toml`, how Python builds
and installs it. Its code is in `src/<package>/`, and the manifest's paths (templates,
migrations, data) start there. An application folder has the same pair: its `module.yml`,
and a `pyproject.toml` that only gathers the Nest packages it runs on.

An application in a repository of its own states what it needs of Nest in its `deps`, by
ecosystem and with versions, as RoboHub's manifests do:

```yaml
deps:
  nest:                  # Nest's own modules, providers and theme
    auth: ">=0.3,<1"
    db-sqlite: ">=0.1,<1"
  saga:                  # the Saga engine and its subsystems
    saga: ">=0.1,<1"
    farm: ">=0.1,<1"
```

A module may be the host of parts: an engine and its subsystems, a module and its
extensions. The host declares what it takes and what comes with it; each part is a package of
its own, with its identity, that names its host and depends on it, so a part made later, in
another repository, joins the host the same way:

```yaml
# the host (engines/saga/module.yml)
subsystems:
  types: [subsystem, content]
  bundled: [world, map, item, ...]
# a part (engines/saga/subsystems/farm/module.yml)
part_of: saga
deps: {saga: ">=0.1,<1"}
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
uv run pytest                             # the tests
uv run nest validate .                    # every manifest against its contract
uv run nest new app myapp --into applications
uv run nest new module glossary --into modules
```

## Where things live

```
packages/nest-core/   the host: manifests, contracts, catalog, resolution, bindings, security, SSE, CLI
modules/              reusable modules (htmx, auth, forms, glossary, content, media, gallery, comments, redirects, forum, messages, trains)
interfaces/           interfaces (cache, db, search, storage)
providers/            providers (cache-memory, db-sqlite, db-postgres, db-mariadb, search-sqlite, storage-local)
themes/               themes (base)
engines/saga/             the Saga engine, a package like any module (module.yml and pyproject.toml, code in src/nest_saga/)
engines/saga/subsystems/  its subsystems, each a package of its own that names the engine (part_of: saga)
applications/             applications (keeper, hello, regionalisme, morlaca, transilpedia, gari)
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

## Search

`nest.search` is an interface. Modules index documents and ask for matches, and the provider
decides how. `search-sqlite` keeps an FTS5 index in the workspace:

* diacritics are folded both ways, so "stiinta" finds "știință" and "ştiinţă" finds both;
* the last word typed matches as a prefix;
* titles rank above bodies;
* snippets are escaped first and then marked.

Whatever someone types is only words, never query syntax. The index is derived data, so
`nest glossary reindex` rebuilds it from the records.

## Glossaries: the regionalisme site

`glossary` holds dictionaries. A dictionary holds terms, and a term holds senses (definition,
usage, synonyms, antonyms, see-also, source, translation, abbreviation), the shape Glossword used.

* **Visitors** browse by letter, read a term with its neighbours, and search every dictionary at once.
* **Editors** (the `editor` role) add, change and remove terms, and each save is indexed.
* **Definitions** are plain text, never HTML: a blank line starts a paragraph, `[[word]]` links a
  term, and an address becomes a link.

`applications/regionalisme` is regionalisme.ro on Nest. With `legacy_glossword: true` in the
application's manifest, Glossword's `/index.php/term/Graiul+moldovenesc,cuvânt.xhtml` addresses
redirect permanently to the new ones.

```sh
uv run nest glossary import-glossword applications/regionalisme export.txt --dictionary "Graiul moldovenesc"
uv run nest glossary dictionaries applications/regionalisme
uv run nest glossary export applications/regionalisme backup.json     # and `import` to restore
uv run nest auth create-user applications/regionalisme ana@example.ro --role editor
uv run nest run applications/regionalisme                             # http://127.0.0.1:8200
```

The import reads Glossword's own text export (Admin → Export). It is safe to run again:
terms already imported are updated, not duplicated.

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
uv run nest content import-wordpress applications/morlaca ~/projects/morlaca/db/morlaca.sql \
    --uploads ~/projects/morlaca/wp-content/uploads
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
uv run nest gallery import-wordpress applications/morlaca ~/projects/morlaca/db/morlaca.sql \
    --uploads ~/projects/morlaca/wp-content/uploads        # --all for galleries no page uses
uv run nest gallery list applications/morlaca
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

Realtime topics can be families (`forum.topic.*`, and later `player.*` for the game). A family's
`authorize(request, name)` sees the concrete name, which is how a member may follow
`messages.user.7` only when they are member 7.

## Trains: gari.ro's timetable

**`trains`** is a railway timetable, reusable by any application:

* **Stations:** departure and arrival boards, amenities, a map link, and, with `gallery`, their
  photos.
* **Trains:** the whole route, with passenger stops and the points a train runs through.
* **Journeys:** direct trains between two stations, with duration, distance and the fare the
  fare table gives per class.
* **Operators**, an A–Z station list, and station names matched without diacritics: "Bucuresti"
  finds "Bucureşti Nord".
* **A railway map:** stations and the links trains run between them, drawn server-side as an
  SVG, with no map library and nothing external.
* **Stations near you:** one small static script asks the browser where it is.

A route is kept as ordered stops whose times count past midnight (`07:40 (+1)`), so night
trains stay in order.

```sh
uv run nest trains import-geticus applications/gari ~/projects/gari/gari/db/gari.sql
uv run nest gallery import-geticus applications/gari ~/projects/gari/gari/db/gari.sql --root ~/projects/gari/gari
uv run nest trains journeys applications/gari "Cluj Napoca" "Bucuresti Nord"
```

`applications/gari` mounts the timetable at `/cfr`, where gari.ro had it (`/cfr/gara/…`,
`/cfr/tren/…`, `/cfr/itinerariu`, `/cfr/companie/…`), and the galleries at `/galerii-foto`, as
Geticus routed them.

## The Saga engine

**Saga** is Nest's engine for life-simulation games: characters, households, settlements and
realms over generations, a text browser game with many players on one server. It is generic:
a game made with it is an application in a repo of its own, with its content pack (its data)
and its client. The first is voievodate.ro (`../voievodate`, a life in the medieval Romanian
lands); Nest may grow other engines beside it in `engines/`. Saga is the **nest-saga
ecosystem**: its engine (`engines/saga/engine`, the `saga` module) publishes a contract adding the **`subsystem`** type, which must declare `tick:`,
so the core validates subsystems as it validates its own types.

* **One World per game server** (`servers`). A world holds what each subsystem keeps, its own
  seeded random generator and its own clock. Two servers share nothing.
* **One loop per world is the only writer.** HTTP handlers `submit` commands and await the
  result. Each tick, the loop:
  1. applies the queued commands;
  2. advances the clock;
  3. runs each subsystem's stage in the order the manifests declare (`tick.after`), at its own
     rate (`tick.every`), timed;
  4. publishes the stages' events on `saga.<server>.<topic>`;
  5. every `checkpoint` seconds (30 by default), writes what changed in every subsystem in
     one transaction, in a thread. That is one fsync for the whole world and a consistent
     snapshot (a crash never leaves the inventory ahead of the characters), and the loop never
     waits on the disk. A checkpoint that fails is kept and written before the next one.
* **Testable by hand.** With `autostart: false` the worlds are stepped by hand (tests, the CLI)
  and behave exactly the same.
* **Game masters** see every server's clock, tick time and stages at the module's route, and
  can pause, resume and step it.

```yaml
# a subsystem's module.yml
type: subsystem
tick: {stage: npc, after: [world, economy], every: 0}
```

```python
class NpcSubsystem(Subsystem):
    def load(self, world, db): ...  # build world.state["npc"] from the database
    def tick(self, world, dt): ...  # dt game seconds; world.rng, world.now, world.emit(...)
    def flush(self, world): ...  # collect what changed; return a writer for a thread
    @handles(TalkToNpc)
    def talk(self, world, command): ...  # applied on the loop, answered to the submitter
```

**Light on small servers.** The target is 1000-2000 players on a basic machine, and the
benchmark (`nest_saga.bench`) measures it. Game masters run it from the admin panel's **Tools** page
(`<admin route>/saga/tools`): it shows progress while it runs, keeps each run's results in the
workspace (`data/bench/`, the newest 50), and compares two runs in a before/after table with the
change. From a terminal, `tools/bench_game.py` does the same.

The benchmark runs in a child process at low priority, one run at a time, in a scratch folder with
its own SQLite database. Its environment is cleared of `NEST_*`, so the live secret and database
credentials stay with the server. It is stopped after `bench_minutes`, and its folder is removed
after. It builds a world of settlements and players, steps it, and
reports each subsystem's tick time and the checkpoints. With 2000 players, 266 NPCs and 612
buildings in 40 settlements:

* A tick takes about 15 ms of work (4 ms characters, 2 ms NPCs, 9 ms production), once a
  second.
* A checkpoint takes about 100 ms every 30 seconds, off the loop. Before, it was a transaction
  per subsystem every 5 to 10 seconds, the characters' alone 230 ms.

The design choices behind that:

* Writers use `nest_saga.store` (`save`, `drop`). It finds existing rows with one query per few
  hundred keys and writes with executemany INSERT and UPDATE, instead of an ORM object per row.
* `Written` remembers what was last written, so only changed columns are sent. A character's
  needs change hourly; its skills rarely do.
* Needs and work advance in steps of at least one game minute. Per-tick lookups (a settlement's
  workstations) are computed once per tick.
* The command queue is bounded (`queue_limit`). A flooded server answers "busy" instead of
  growing without limit.


**`world`** is the first subsystem ported. It keeps the game calendar (a restarted world goes on
where it was), the season by month, and each day's weather for the world and its regions, drawn
with the world's seeded generator. Clients follow `saga.<server>.world` for `clock` and
`weather`.

**Content packs** (type `content`) are the game's data as YAML: no code, no tick, read once at
start. A game keeps its pack in its own repo, as a local module of its application
(voievodate's is `modules/voievodate-content`, with the tools that rebuild its YAML from
flasknest-core's seeds). Packs load in the order the application lists them, and a later pack
redefines an item by its slug, so a server can override a game's data without copying it.

**`item`** reads every pack's `items:` into one catalogue: weight, value, durability and wear,
uses, effects, what an item is made of, and what a container leaves when it is empty. The other
subsystems get it with `catalogue_of(host)`. Broken references are reported at start, not
fatal. The original seeds had one: herbal tea leaves a `clay-cup` that no seed defines.

**`inventory`** holds who has what (`inventory_stack`). An owner is any `(type, id)`, such as an
npc, a player, a household or a guild. Each stack also has a location, which defaults to the
owner's person or vault. Alike things pile up in one stack. Tools and other items with
durability or several uses are kept unit by unit, each with its own wear. Taking is all or
nothing, and the most worn units go first. A water skin's last drink leaves the empty skin.
Stacks are written by key at each checkpoint. Game masters can follow each owner's
`saga.<server>.inventory.<type>.<id>`. The commands are `GiveItem`, `TakeItem` and
`TransferItem`.

**`character`** is what NPCs and players are. Its definitions come from the packs' `characters:`
files: attributes, skills, technologies, emotions, traits, the 18 professions and their ranks,
social ranks, and 16 diseases with their effects and treatments. A character has a single sheet
(`character_sheet`, its values kept as JSON), whether it is an NPC or a player. The npc and
player subsystems will add a mind on top.

* **Needs:** every living character gets hungry, thirsty and tired by the game hour (settings),
  so a world runs the same at any tick or time scale. Rest and sleep restore stamina. At full
  hunger or thirst, health falls.
* **Emotions** follow voievodate's rules: feelings fade, want brings sadness, anger and fear,
  and comfort brings joy.
* **Diseases** incubate, hurt every few hours, progress, and roll once for death at 80%.
  Contagious ones spread between characters in the same place, using the world's seeded
  generator. A treatment is given once (an item used, a healer, rest) and rolls its
  effectiveness.
* **Healing:** health and carry weight recover when no disease affects them. The old engine had
  no healing.

The old seed list forgot the diseases. The seed tool now runs that seed too, and the export
maps the treatments' placeholder item (`item_id=16`, the iron hammer) to the items their
comments name. The commands are `CreateCharacter`, `Infect`, `Treat`, `GrantExperience` and
`ChangeAttribute`. Game masters follow `saga.<server>.character` for births, deaths and
illnesses, and `saga.<server>.character.<id>` for one character's sheet.

**`map`** is the land: every tile's terrain and county, and the regions above (county, duchy,
principality, kingdom). The voievodate pack bakes them once with `tools/export_map.py`, from
the old engine's 65 county outlines:

* `regions.yml` holds the regions, with outlines and colours to draw.
* `map.bin` holds 501 × 501 tiles of two bytes each, gzipped to 9 KB. The game holds it in memory,
  so a tile's county is an index into bytes.

The old engine kept 251,001 tile rows in a table and parsed the outlines with shapely at every
boot. Other subsystems ask `map_of(host)`: `at(x, y)`, `region(x, y)`, `tiles_of(county)`. A
settlement's region is the county it stands in. With `places: true` (voievodate sets it), a new
world begins with one settlement in each county, named for its seat; their founders arrive with
them. Game masters see the land in the admin panel (`<admin route>/saga/map`): the counties in their duchies' colours, and
a dot for each settlement sized by its people, refreshed while the page is open.

**`settlement`** keeps the hamlets, villages and towns: where each is (map tiles), its
residents, treasury, prosperity and technologies. Once a game day it counts its living
residents: the population, plus ages, genders, ranks and professions. It then evolves to the
next type when it meets its rule: population, prosperity, base buildings and technologies. The
old engine kept these rules in code; they are now in `settlements.yml`. The commands are
`FoundSettlement`, `Settle` and `AdjustSettlement`.

**`building`** raises buildings (`buildings.yml`: 29 buildings, 10 attributes, construction
materials, 7 upgrades).

* **Condition** is the weighted mean of a building's attributes.
* **Grants:** every settlement gets, free, what its type grants: a hamlet a well and a church,
  a village a market stall. This follows what the old engine built.
* **Raising** a building otherwise takes the construction materials from the owner's
  inventory.
* **Upgrades** go in order, cost their materials and gold (a character's money or a
  settlement's treasury) and take their game hours.
* **Decay:** buildings decay by game day and year, using voievodate's odds and the world's
  generator. Storms damage roofs. Wells improve the water supply, sanitation and fire
  protection around them; the old code meant to, but no building was tagged.

The commands are `RaiseBuilding`, `StartUpgrade` and `RepairBuilding`. Settlements and
buildings are public, so anyone may follow `saga.<server>.settlement[.<id>]` and
`saga.<server>.building[.<settlement id>]`.

The checks at start report what the original data lacks. Settlement evolution past a village
asks for technologies no pack defines (`basic_trade`, `trade_routes`, `stone_masonry`,
`advanced_civil_engineering`), and a city is granted a `cathedral` that is no building.
Placement by terrain waits for the map, voievodate's 501 × 501 tiles.

**`npc`** gives NPCs a mind. Its data is in `npc.yml`: 26 GOAP actions, 9 conscience rules, and
each profession's work, skill, workplace and schedule by season. Names, founders and provisions
are there too.

* **When to decide:** an NPC decides when its action ends, or at once when hunger or thirst pass
  70.
* **What to choose:** the schedule's activity for the game hour and season scores 0.5. Each
  rule that holds adds its weight to an intent (thirst over 70 adds 10 to drink). The best
  intent that can be planned wins.
* **Planning:** the planner chains back through the actions' preconditions. To eat without
  food, an NPC takes some from home or forages. Emotions and traits tilt the costs.
* **Doing:** the NPC walks to where the action happens (home, workplace, well, market, the
  wild) at a walking speed, then spends the action's game minutes there. Work trains the
  profession's skill. Meals and drinks go on until sated.
* **Founders:** a new settlement is peopled with the professions every settlement has (farmer,
  hunter, woodcutter, fisher, merchant) and a few more. Each founder gets a home, a workplace
  and provisions.

The old engine's schedules read the wall clock's hour; Nest's follow the game's hour and
season. The old GOAP list had no way to eat or drink before there was a market; Nest adds two
actions from the old game's own data: the well's "Drink Water" and the "Gather Food" activity
(foraging). The seeds' schedule-skip rules on work said to skip working while fed
(`hunger_min: 20`); those are dropped, because the preconditions already stop a hungry worker.
Buying waits for the economy. Anyone may follow `saga.<server>.npc.<settlement id>`: where each
NPC is and what it does, with its walk (from, to, depart, arrive) for a client to animate.

**`production`** is what workers make. Its data is `production.yml`: 82 recipes, what each
trade keeps, and the seasons' effect on output.

* **Working:** while an NPC works (its profession's activity, at its workplace), its job
  advances by game minutes. Skill makes it faster, 2% a level.
* **Choosing:** a worker makes the recipe of its trade that yields most. If one is stopped only
  by something a common recipe gives (water, for the baker's bread), it does that first. It
  chooses again after each making.
* **Finishing:** a finished recipe takes its inputs (from the worker, else the settlement's
  store), wears its tools and gives its outputs by the season. It also gives the recipe's
  experience.
* **The store:** beyond what the trade keeps (a farmer 20 wheat), the outputs go to the
  settlement's store. Bakers take flour from it and the hungry take food (a new NPC action). It
  is a commons until the economy puts prices on things.
* **Kits:** a new worker gets the tools of its trade's first recipes, and founders know their
  trade at level 1.

The old engine gave no tools, and its recipes asked for skill levels nobody could reach, so it
never produced. The original data also had these gaps:

* Recipes ask for ten skills no pack defines (baking, smithing...); those are reported and not
  asked.
* Nothing made water, so drawing it at the well is added.
* Four first recipes took 100 minutes where their kin take 6 to 10, so they are taken as 10.
* Herders' recipes want a barn, so their buildings now have one.
* Tools still break by the old arithmetic (a bow lasts six hunts). Replacing them waits for the
  economy and the blacksmith.

Anyone may follow `saga.<server>.production.<settlement id>` to watch the store.

**`economy`** sets what things are worth and gives every settlement a market. Its data is
`economy.yml`: the wage, the spread, the seasons and the old price limits.

* **Values come from labour:** an item's cheapest recipe, at a wage, plus its inputs' values and
  its tools' wear, through the whole chain. Bread is flour, water and the baker's time
  (wheat 1.00, flour 1.84, bread 2.21). Items no recipe makes get a value from their type and
  effects.
* **Markets hold real goods** (an inventory owner, `("market", id)`) and trade from the
  settlement's treasury, so money moves between people and is never made from nothing.
* **Prices:** a price is the value moved by scarcity (stock against recent demand), the season
  and a spread, worked out when asked.
* **Who trades:** workers sell what their trade does not keep, as much as the market wants and
  can pay for. The hungry buy the food that feeds most for the money (`go_buy_food`, playable
  now). Workers buy back broken tools.
* **Merchants:** once a game day, a settlement's merchant brings what its workers lack (a broken
  tool) and sends away surpluses, for a commission. Money paid to and earned from the world
  beyond is the only money that enters or leaves.

The old engine began every item's price at 1.0, with limits for eleven, and its market paid
sellers from nothing. Not yet here: taxes (with the settlement's laws), and demand for logs,
clay and wool, which wait for builders and crafts. Anyone may follow
`saga.<server>.economy.<settlement id>` for the market's goods and prices, at most once a game
hour.

**`household`** makes families. Every resident NPC belongs to a household, with the roles from
`households.yml`.

* **Marriage:** once a game day, unmarried adults of a settlement may marry. The spouse moves
  into the head's home.
* **Children:** married couples may have children, characters born at 0. Under 12 their family
  feeds them every hour from what it holds, else buys food with the purse or a parent's money,
  and brings water from the well. At 12 they get a mind of their own. At 16 they take up the
  head's trade at the head's workplace, and production equips them.
* **The purse:** members give a fifth of what they hold beyond 100 coins. Those short of money
  are given an allowance, and a worker whose tool broke may draw the rest of its price.
* **Death:** the headship passes to the spouse, then the eldest child, then a relative. An
  emptied household leaves its purse to the settlement.
* **Old age:** characters now also die of it (the `old_age` setting), so a land that is born
  into also dies.

Two-year simulations showed what a settlement needs to live, and set these rules:

* An hour of work costs a quarter of an action's effects; the seeds' numbers are a working
  session's.
* A producer of food keeps two days' eating of it.
* Workers take their surplus to market once a game day, not only when they make something.
* A purchase of food buys a full meal and the next.
* A merchant's caravan buys surpluses for export, up to 300 coins a day, so producers of logs,
  clay or wool earn and money enters the land. Food is never exported.

Not yet: animals, fields and winter firewood from the old household data.

**`law`** gives each settlement its own taxes and laws (`law.yml`, from the old seeds by
`tools/export_law.py`).

* **Taxes:** each tax says what it falls on, and it is collected:
  * a share of what is made, in kind, to the market (the grain tithe, the miller's toll);
  * a share of what the market pays sellers (market dues, the tavern tax);
  * a share of craftsmen's money once a year.

  The old engine looked its taxes up as "income" and "trade", which none was called, so none
  was ever collected.
* **Laws:** a law's enforcement is the chance an offender is caught, and its severity the
  punishment: a fine, lashes or the pillory. The starving poor steal food at the market (a new
  NPC action), so theft has thieves. The old crime detection was an empty loop.
* **Alms:** once a game day the treasury relieves the poor, from what it holds beyond its reserve.
  A treasury that only took starved its settlement of coin.
* **Commands:** `SetTax` and `SetLaw`.

Judges, trials, councils and elections wait for the government.

**`religion`** gives everyone a faith (`religion.yml`, from the old seeds by
`tools/export_religion.py`). It comes from the region they live in (the old weights: Transylvania
and the Banat 30% Catholic) or from their household's head.

* **Worship:** on Sundays and major feasts the faithful of a settlement with a church of their
  faith gather, and their piety and happiness rise. A church serves the faith most of its
  settlement keeps. A week away costs a point of piety; priests keep theirs.
* **The calendar** is the Julian, as the Romanian lands kept it throughout 1100-1600. Weekdays
  come from the Julian Day Number. Easter follows the Julian computus for every church until the
  reform of 1582, and the Gregorian for Catholics after it, given in Julian dates.
* **Corrections to the old data:** Christmas is 25 December, not today's 7 January. The Order of
  the Dragon was Sigismund's Catholic order (1408), not an Orthodox one.

Game masters see each settlement's faiths, their piety and the year's feasts in the admin panel.

A game runs from its own repo (with Nest checked out beside it), for voievodate:

```sh
cd ../voievodate
uv run nest saga status .
uv run nest saga step . voievodate 3600     # one game day at 24×
uv run nest run .                            # http://127.0.0.1:8500/joc
```

The keeper still sees it: its `apps` setting lists `../voievodate`, a folder that is an
application, so the game is planned, checked and probed with Nest's own applications.

## The admin panel

Every application has one admin panel, made of what the application is made of. The `admin`
module is the shell, included once at a route (`/admin`). Each module gives it its own pages,
with `host.admin(router)`, and says in its manifest how they are listed:

```yaml
# a module's module.yml
admin: {title: Content, order: 10, role: editor, description: Pages, articles and menus.}
```

The panel mounts each module's pages at `<admin route>/<module>`: `/admin/content`,
`/admin/redirects`, `/admin/game`. It shows each user a menu and a front page with only the pages
their roles open (the `admin` role opens all). A module's admin templates extend
`admin/layout.html`, and links come from `admin_url(request, module, path)`.

So morlaca and transilpedia, made of the same modules, have the same panel. The game has the
game's panel: its servers, its land and its tools (`/admin/game`). No panel is written for an
application, and an application without the admin module serves no admin pages (it says so at
start). A module whose pages are all in the panel needs no route of its own (redirects).

## The keeper

`applications/keeper` is Nest's own application, at port 8000. It orchestrates the applications
and covers what is generic to them. What is specific to one application is in that application's
admin panel. The keeper finds applications in two ways:

* installed packages of type application, which is how a site in a repository of its own is seen;
* the folders of its `apps` setting (`applications` by default).

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
