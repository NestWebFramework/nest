---
title: "The manifest: module.yml"
description: "Every key of module.yml for modules, themes, providers, interfaces and applications, the contracts each type keeps, and nest validate."
---

# The manifest: module.yml

Every package Nest knows is described by one `module.yml`: a module, a theme, a
provider, an interface, an application. Nest reads it before importing anything, so
the plan of an application (what it includes, in which order, bound to what) and every
reason it cannot run are known before any code runs.

The manifest is read into a typed model (`nest/manifest.py`). A typo inside a known
section is an error, not a silently ignored key. Unknown **top-level** sections are kept,
so a module or an ecosystem can read sections of its own (`db:`, `admin:`, `csp:` below
are such sections).

## A module's manifest

The glossary's, shortened:

```yaml
module:
  name: glossary
  id: nest.module.glossary
  type: module
  title: Glossary
  category: content
  version: 0.1.0
  description: Dictionaries of terms with senses.
  license: MIT
  created: "2026-11-13"

nest: ">=0.2,<1"

main: nest_glossary
styles: [glossary.css]

provides:
  import: nest_glossary
  exports: [KIND, SenseData, Urls]

requires:
  interfaces: [nest.db, nest.search]

deps:
  db: ">=0.2,<1"
  search: ">=0.1,<1"
  auth: ">=0.2,<1"

db:
  migrations: migrations
  metadata: "nest_glossary.models:Base"

settings:
  per_page:
    type: int
    default: 100
    description: Terms per page in a letter's list.

locales:
  - {locale: ro, file: locales/ro.json}
  - {locale: en, file: locales/en.json}

admin:
  title: Dictionaries
  order: 12
  role: editor

docs:
  title: Glossary
  section: modules
```

## module: the identity

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | the identity: lower-case and dotted (`nest.module.glossary`) |
| `name` | yes | how applications and other manifests refer to it: lower-case letters, digits, `-`, `_` |
| `type` | yes | `module`, `theme`, `provider`, `interface`, `application`, or a type an ecosystem's contract adds |
| `version` | yes | a PEP 440 version (`0.1.0`) |
| `title` | no | the name people read (admin panel, reference pages) |
| `description` | no | one or two sentences |
| `category` | no | a grouping shown on reference pages (`content`, `community`, `maps`) |
| `license` | no | an SPDX name (`MIT`) |
| `maintainer`, `created` | no | who looks after it; when it was made (quote the date) |
| `previous_ids` | no | ids it had before, so bindings written with an old id still find it |

## What a package gives and needs

| Key | Meaning |
|---|---|
| `nest` | the nest-core versions it works with (`">=0.2,<1"`). A registry refuses a package without it; an application whose nest-core is outside it does not start |
| `main` | the Python module Nest imports; for a module, its `setup(host)` is called; for a provider, its `create(settings, context)` |
| `provides.import` | the import path other code uses |
| `provides.exports` | the names in it other packages may use; `nest validate --strict` checks code keeps to them |
| `requires.interfaces` | interfaces it needs (`nest.db`): the application must bind them, and `host.bound()` refuses any other |
| `requires.host` | host facilities it uses: `workspace` (the application's folder of files) and `realtime` (server-sent events). Anything else is a plan error; using one not listed is a setup error |
| `deps` | packages it depends on, by name, each with a version range (`""` or `"*"`: any). They are started before it |
| `uses` | optional partners: started before it when the application includes them, never pulled in (`uses: [translations]`) |
| `implements` | for a provider, the interfaces it answers (`[nest.db]`) |
| `interface` | for an interface, its `name` (dotted, `nest.db`) and `protocol` (`"nest_db:Database"`) |

`deps` may be grouped by ecosystem, as an application does; the plan then checks each
dependency belongs to the ecosystem it is listed under:

```yaml
deps:
  nest:
    trains: ">=0.1,<1"
    auth: ">=0.3,<1"
```

## settings

Each setting is typed, so a wrong value stops the start with a clear message instead of
failing later.

| Key | Default | Meaning |
|---|---|---|
| `type` | `str` | `str`, `int`, `float` or `bool` |
| `default` | none | the value when nothing else sets it |
| `choices` | none | the only values allowed (`[none, guests, all]`) |
| `required` | `false` | the application or the environment must set it |
| `secret` | `false` | set in the environment only, never in a manifest or the admin panel; a secret cannot have a default |
| `label` | none | what the admin panel's settings page calls it |
| `description` | none | the help text beside it |
| `editable` | `true` | shown in the admin panel to change (`false`: set in module.yml or the environment) |
| `restart` | `false` | read when the module is set up (its routes depend on it): a change applies when the application is made again |

Setting names are snake_case. The environment variable for a setting is
`NEST_<APP>__<OWNER>__<KEY>`, upper-case, other characters as `_`: the trains module's
secret `legacy_key` in the application `gari` is `NEST_GARI__TRAINS__LEGACY_KEY`; the
PostgreSQL provider's password is `NEST_GARI__DB_POSTGRES__PASSWORD`.

## Files: templates, static, styles, locales

| Key | Meaning |
|---|---|
| `templates` | its templates folder (default: `templates/` when it exists) |
| `static` | its static folder (default: `static/` when it exists), served at `/assets/<name>/` |
| `styles` | stylesheets in its static folder, bundled into the site's one stylesheet: a module's base look, built on the theme's tokens; an application's own, loaded last |
| `admin_styles` | stylesheets for the admin panel only |
| `locales` | its catalogs: a list of `{locale: ro, file: locales/ro.json}`. A catalog not listed is not loaded, so an unfinished translation stays out |

A stylesheet named in `styles` that the static folder lacks is a plan error. See
[templates and assets](templates-and-assets.md).

## Sections modules read

These are not typed by the core model; the package that reads them gives them meaning.

| Section | Read by | Keys |
|---|---|---|
| `db` | the `nest.db` interface | `migrations` (the folder with `versions/`), `metadata` (`package.module:Base`, for `--autogenerate`). See [database](database.md) |
| `admin` | `host.admin()` | `title`, `order` (default 50), `role` (who sees it, default `admin`), `description` |
| `csp` | the host | sources the page policy takes for `img-src`, `frame-src`, `media-src`, `connect-src` (https only). See [security](security.md) |
| `pages` | the plan | `pages: false`: a module with no page of its own, included without a route (seo, notifications) |
| `translatable` | the translations module | records whose text is kept per language: `model`, `label`, `fields`, `title`, `edit` |
| `docs` | the registry, the docs site | `title`, `section` |
| `redirect_prefixes` | the redirects module | `{"/old/": "/new/"}` folder moves |

A module included without a route is a plan error unless it has an `admin:` section or
`pages: false`.

## Hooks and process hints

| Key | Meaning |
|---|---|
| `startup` | `package.module:function`, called as `fn(nest)` once bindings exist and before any module is set up (the db interface migrates there) |
| `forget` | `package.module:function`, called as `fn(nest, entry)` for every package uninstalled from the application (the db interface drops its tables) |
| `one_process` | its state lives in its process (a game engine's worlds): the application runs as one process while it has it |
| `process_local` | a provider whose values live in each process (cache-memory): `host.bound_if(..., shared=True)` skips it |
| `subsystems` | a module that hosts parts: `types` (default `[subsystem]`), `bundled` (part names) |
| `part_of` | a part names the module it belongs to (and depends on it) |
| `system_deps` | system packages it needs, kept as written |

## Themes

A theme is a package of type `theme`: templates, a stylesheet and settings.

| Key | Meaning |
|---|---|
| `extends` | the theme it is built on: its templates and stylesheet fill what this one lacks. It must be in `deps` too |
| `styles` | the theme's stylesheet, first in the bundle |
| `settings` | what an application may set for it (`application.theme_settings`) |
| `preview` | colours its card in the admin panel's Themes page shows (`bg`, `surface`, `text`, `muted`, `accent`, `border`) |

The theme contract (the templates and blocks every theme provides) is described in
[templates and assets](templates-and-assets.md) and [themes](../themes.md).

## Applications

An application composes modules, binds interfaces, and runs on one port.

```yaml
module:
  name: docsite
  id: nest.app.docsite
  type: application
  version: 0.1.0

application:
  title: Nest
  port: 8700
  theme: paper
  languages: [en]

modules:
  - name: docs
    route: /docs
    core: true
    config:
      tree: ../../docs
  - {name: admin, route: /admin, core: true}
  - name: auth
    route: /cont
    config: {allow_registration: false}

bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
```

| Key under `application:` | Default | Meaning |
|---|---|---|
| `title` | the module title | the site's name |
| `port` | none | the port `nest run` and `nest serve` listen on |
| `theme` | none | the theme it starts with (the administrator may choose another) |
| `languages`, `default_language` | `[en]`, the first | the site's languages |
| `admin_languages` | the site's | the languages its admin panel can be read in |
| `browser_language` | `true` | speak the browser's language before a visitor chooses |
| `language_urls` | `cookie` | `cookie` (one address) or `prefix` (`/en/...` per language) |
| `theme_settings` | `{}` | settings by theme: `{rail-signage: {tagline: "..."}}` |
| `max_body_mb` | `32` | the largest request body, in MB (`NEST_MAX_BODY_MB` wins) |
| `admin_frame` | `standalone` | the admin panel as a page of its own, or `site` (in the site's theme) |

| Key of a `modules:` entry | Meaning |
|---|---|
| `name` | the package |
| `route` | where it serves its pages; starts with `/` |
| `enabled` | `false`: listed but off until the administrator turns it on |
| `core` | never disabled or uninstalled, nor anything it depends on |
| `optional` | if its setup fails, the application starts without it |
| `config` | values for its settings (never secrets) |

`bind:` maps an interface to `providers` (the first answers `host.bound`), optional
`alternatives` the environment may choose instead (`NEST_BIND__NEST_DB=db-postgres`), and
`config` per provider. `deploy:` (`port`, `service`, `calls`) and `serve:` (`workers`,
`threads`, `timeout`, `graceful_timeout`, `keepalive`, `max_requests`,
`max_requests_jitter`) are read by the deployment tools; see [deploy](../deploy.md).

## Contracts

A contract says, per type, which sections a manifest must carry and which it must not.
The core contract is `packages/nest-core/src/nest/contracts/core.v1.yml`:

| Type | Must declare | Must not declare |
|---|---|---|
| `module` | `main` | `application`, `modules`, `bind`, `deploy` |
| `interface` | `interface` | `implements`, `application`, `modules`, `bind` |
| `provider` | `main`, `implements` | `application`, `modules`, `bind` |
| `theme` | nothing | `application`, `modules`, `bind`, `implements` |
| `application` | `application` | `implements`, `provides`, `interface`, `part_of`, `subsystems` |

Each forbidden section carries its reason, and `nest validate` prints it: "a module must
not declare 'bind': only an application binds interfaces to providers". An ecosystem
publishes its own contract (new types, or refined ones) through the `nest.contracts`
entry point; contracts are merged, a later one refining an earlier one.

## nest validate

```sh
uv run nest validate                 # every module.yml under the current folder
uv run nest validate modules/quiz    # one package, or several paths
uv run nest validate --strict .      # also: code keeps to the manifests, themes keep their contract
```

It reads each manifest, checks it against the contract of its type, and exits 1 when any
has a problem. `--strict` adds the boundary checks (`nest/boundaries.py`): a package
imports only what it depends on and only the names others export, and every theme keeps
the theme contract.
