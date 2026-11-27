---
title: "A module from scratch"
description: "Scaffold a Nest module, understand its package layout, mount its routes, keep its state, read its settings and include it in an application."
---

# A module from scratch

A module is a Python package with a `module.yml` beside its code. It owns no port: an
application includes it at a route and gives it a `ModuleHost`, its view of the running
application. This page builds one with the scaffold, then walks through a real module
(the forum) to show each part a module usually has.

## Scaffold it

From the root of the Nest repository:

```sh
uv run nest new module quiz --into modules
```

A name is lower-case letters, digits and `-`. The command writes:

```
modules/quiz/
  pyproject.toml                  the Python distribution (nest-quiz)
  src/nest_quiz/
    module.yml                    the Nest manifest
    __init__.py                   setup(host): what the module does at startup
    templates/index.html          its first page
```

The generated `pyproject.toml` declares the entry point Nest finds the package by:

```toml
[project]
name = "nest-quiz"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["nest-core"]

[project.entry-points."nest.modules"]
quiz = "nest_quiz"

[build-system]
requires = ["uv_build>=0.9,<0.14"]
build-backend = "uv_build"
```

Nest discovers installed packages through the `nest.modules` entry point, and also an
application's own `modules/*/module.yml` (code that belongs to one application only). The
Nest repository is a uv workspace whose members include `modules/*`; to install a new
module there, add `nest-quiz` to the root `pyproject.toml` dependencies and
`[tool.uv.sources]` (as the other modules are), then `uv sync`.

Check the manifest at once:

```sh
uv run nest validate modules/quiz
```

> [!TIP]
> `uv run nest new app NAME --into applications` scaffolds an application with one local
> module mounted at `/`: the quickest way to try a module is to add it to that.

## The package layout

A packaged module keeps `module.yml` beside its Python code, in `src/nest_<name>/`. Every
relative path in the manifest starts there, so the conventional folders sit next to
`__init__.py`:

| Path | What it holds | Declared in module.yml |
|---|---|---|
| `module.yml` | identity, settings, dependencies | — |
| `__init__.py` | `setup(host)`; the public API listed in `provides.exports` | `main`, `provides` |
| `templates/` | Jinja templates, reached as `"<module>/<file>"` | found by convention (`templates:` to rename) |
| `static/` | CSS, JS, images, served at `/assets/<module>/` | found by convention (`static:` to rename) |
| `locales/*.json` | translations, one catalog per language | `locales:` |
| `migrations/versions/` | Alembic revisions, for a module with tables | `db.migrations` |

See [the manifest reference](manifest.md) for every key.

## setup(host)

When the application starts, Nest imports the module named in `main` and calls its
`setup(host)` once. Everything a module registers happens there: routers, admin pages,
lookups it answers, template context, background tasks. The scaffold's version:

```python
from fastapi import APIRouter, Request

from nest import ModuleHost, render

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return render(request, "quiz/index.html")


def setup(host: ModuleHost) -> None:
    host.mount(router)
```

A module that fails in `setup` stops the application from starting, unless the
application includes it with `optional: true`; then the application starts without it
and its health page says why.

## Mounting routes

| Call | Where the router is served |
|---|---|
| `host.mount(router)` | at the route the application chose (`route: /quiz`); `HostError` without one |
| `host.admin(router)` | in the admin panel, at `<admin route>/<module>`; title, order and role come from the manifest's `admin:` block |
| `host.serve_at_root(router)` | at the site's root whatever the module's route, for fixed addresses (`/sitemap.xml`, `/robots.txt`) |
| `host.fallback(fn, priority=0)` | not a router: asked for a GET no route matched (see [lookups](lookups.md)) |

Every router mounted this way gets CSRF protection on its unsafe methods (see
[security](security.md)). `host.mount(router, csrf=False)` exists only for an API whose
clients send a bearer token on every request, never a cookie.

The module never hard-codes its route: `host.route` is what the application chose
(`None` when it included the module without one) and `host.url("path")` builds an address
under it.

## Run-time state: host.state and host.live

A module keeps what its handlers need in `host.state`, a dict that belongs to this
module in this application, never in module-level globals (two applications in one
process, or one test after another, must not share it). Handlers read it back with
`nest.host.module_state(request, "<module>")`.

A value made with `host.live(key, kind)` is a setting read again each time it is asked
for, so a change made in the admin panel applies at once, without a restart. The forum's
`setup`, shortened:

```python
from nest import ModuleHost


def setup(host: ModuleHost) -> None:
    from nest_forum.web import router

    host.state.update(
        base="" if host.route in (None, "/") else host.route,
        public_read=host.live("public_read", bool),
        edit_minutes=host.live("edit_minutes", int),
        topics_per_page=host.live("topics_per_page", int),
        posts_per_minute=host.live("posts_per_minute", int),
        realtime=host.realtime,
    )
    host.mount(router)
```

and a handler in `web.py`, shortened:

```python
from fastapi import APIRouter, Request
from nest_db import Database

from nest import bound, render
from nest.host import module_state

router = APIRouter()


@router.get("/{slug}/")
def board_page(request: Request, slug: str, db: Database = bound(Database)):
    state = module_state(request, "forum")
    b = _board_or_404(request, service.board(db, slug))
    per_page = state["topics_per_page"]  # a live setting, read now
    rows, total = service.topics(db, b.id, page=_page(request), per_page=per_page)
    return render(
        request,
        "forum/board.html",
        fragment="topics",
        board=b,
        topics=rows,
        base=state["base"],
        # ...
    )
```

`host.settings.get(key)` reads a setting once. Use it for values the module's routes
depend on at setup (the auth module reads `session_days` once, when it sets up its
sessions); declare such a setting with `restart: true` so the admin panel
says a change applies when the application is made again.

## What else the host offers

| Member | Use |
|---|---|
| `host.name`, `host.version`, `host.route`, `host.manifest` | who and where the module is |
| `host.config` | what the application's manifest sets for it under `config:` |
| `host.settings` | its own settings, `get` and `set` (namespaced as `<module>.<key>`) |
| `host.log` | a logger named `nest.<module>` |
| `host.production` | `NEST_ENV=production` |
| `host.languages`, `host.default_language`, `host.translator(locale)` | the site's languages, and its words outside a request |
| `host.bound("nest.db")` | the provider of an interface listed in `requires.interfaces` |
| `host.bound_if("nest.cache", shared=True)` | an interface the module can do without, or `None` |
| `host.workspace`, `host.realtime` | host facilities, only when listed in `requires.host` |
| `host.sign(value)`, `host.unsign(token)` | signed values, keyed per module (see [security](security.md)) |
| `host.context(fn)` | values for every page's template context |
| `host.template_filter(name, fn)` | a Jinja filter for every template |
| `host.answer`, `host.lookup`, `host.gather`, `host.shortcode` | cooperating with other modules ([lookups](lookups.md)) |
| `host.on_startup(fn)`, `host.on_shutdown(fn)`, `host.background(...)` | lifecycle hooks and long-running tasks |
| `host.has_module(name)` | whether the application includes another package |
| `host.sections(key)` | a top-level manifest section as every package writes it |
| `host.check_settings(fn)` | judge a settings change before the admin panel saves it |
| `host.allow_source(directive, source)` | widen the page policy at run time ([security](security.md)) |

## Template context

`host.context(fn)` adds values to every page rendered in the application, not only the
module's own. The geo module tells every template where its page is, so a theme can link
to it without knowing the application:

```python
from typing import Any


def setup(host: ModuleHost) -> None:
    from nest_geo.web import router

    host.state.update(
        url="" if host.route in (None, "/") else host.route.rstrip("/"),
        radius_km=host.live("radius_km", int),
        limit=host.live("limit", int),
        gather=host.gather,
    )

    @host.context
    def _geo(request: Any) -> dict[str, Any]:
        url = host.state["url"]
        return {"geo_page": f"{url}/" if host.route is not None else None}

    if host.route is not None:
        host.mount(router)
```

A context function runs for every page; keep it cheap, or return functions the template
calls only when it needs them (the content module returns `menu(slug)`, which reads a
menu only when a template shows it).

## Settings

Settings are declared in `module.yml`, typed and checked at startup:

```yaml
settings:
  public_read:
    type: bool
    default: true
    description: Whether people who have not signed in may read.
  posts_per_minute:
    type: int
    default: 5
    description: Posts a member may send per minute.
```

A value is found, in this order: the environment (`NEST_<APP>__<MODULE>__<KEY>`, read-only
then), the workspace's `data/settings.conf` (what the admin panel saves), the application
manifest's `config:` for the module, the declared default.

## Include it in an application

An application lists the module under `modules:` with a route, and may set its settings:

```yaml
modules:
  - name: forum
    route: /forum
    config:
      posts_per_minute: 3
  - name: comments
    route: /comentarii
```

If the application's manifest declares `deps:`, it lists every package it uses there,
by ecosystem and with a version range:

```yaml
deps:
  nest:
    forum: ">=0.2,<1"
    comments: ">=0.1,<1"
```

Then `uv run nest plan APP` shows the packages in start order and their bindings, and
`uv run nest run APP --reload` serves it. The forum asks whichever module answers the
`forum.access` lookup who may read its private boards; without a module answering it,
those boards stay closed to everyone but moderators, and the forum does not fail. That is the subject of
[the next page](lookups.md).

## Where to go next

- [The manifest](manifest.md): every key of `module.yml`.
- [Lookups](lookups.md): cooperating with other modules without importing them.
- [Database](database.md): tables, migrations, translated text, search.
- [Templates and assets](templates-and-assets.md): pages, fragments, styles, translations.
- [Testing](testing.md): an application in a temporary workspace.
