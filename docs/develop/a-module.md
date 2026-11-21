---
title: "A module from scratch"
description: "Scaffold a Nest module, understand its package layout, mount its routes, keep its state, read its settings and include it in an application."
---

# A module from scratch

A module is a Python package with a `module.yml` beside its code. It owns no port: an
application includes it at a route and gives it a `ModuleHost`, its view of the running
application. This page builds one with the scaffold, then walks through a real module
(hangman) to show each part a module usually has.

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
for, so a change made in the admin panel applies at once, without a restart. Hangman's
`setup`, as it is:

```python
from nest import ModuleHost


def setup(host: ModuleHost) -> None:
    host.state.update(
        url="" if host.route in (None, "/") else host.route.rstrip("/"),
        alphabet=host.live("alphabet", lambda v: [x for x in str(v or "").split() if x]),
        max_wrong=host.live("max_wrong", int),
        min_letters=host.live("min_letters", int),
        max_letters=host.live("max_letters", int),
        show_clue=host.live("show_clue", bool),
        sign=host.sign,
        unsign=host.unsign,
        lookup=host.lookup,
    )
    from nest_hangman.web import router

    host.mount(router)
```

and a handler in `web.py`:

```python
from fastapi import APIRouter, Request

from nest import is_htmx, render
from nest.host import module_state

router = APIRouter()


@router.get("/")
def play(request: Request):
    state = module_state(request, "hangman")
    game, word = _current(request)
    return render(
        request,
        "hangman/play.html",
        fragment="game" if is_htmx(request) else None,
        action=state["url"],
        word=word,
        max_wrong=state["max_wrong"],  # a live setting, read now
        # ...
    )
```

`host.settings.get(key)` reads a setting once. Use it for values the module's routes
depend on at setup (the glossary mounts its legacy router only when
`legacy_glossword` is on); declare such a setting with `restart: true` so the admin panel
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
calls only when it needs them (the glossary returns `gl_title(d)`, which reads the
translated titles once per page, on first use).

## Settings

Settings are declared in `module.yml`, typed and checked at startup:

```yaml
settings:
  max_wrong:
    type: int
    default: 6
    description: Wrong guesses before the game is lost (the drawing has six parts).
  show_clue:
    type: bool
    default: true
    description: Show the word's meaning as a clue.
```

A value is found, in this order: the environment (`NEST_<APP>__<MODULE>__<KEY>`, read-only
then), the workspace's `data/settings.conf` (what the admin panel saves), the application
manifest's `config:` for the module, the declared default.

## Include it in an application

An application lists the module under `modules:` with a route, and may set its settings:

```yaml
modules:
  - name: hangman
    route: /spanzuratoarea
    config:
      max_wrong: 8
  - name: glossary
    route: /
```

If the application's manifest declares `deps:`, it lists every package it uses there,
by ecosystem and with a version range:

```yaml
deps:
  nest:
    hangman: ">=0.1,<1"
    glossary: ">=0.1,<1"
```

Then `uv run nest plan APP` shows the packages in start order and their bindings, and
`uv run nest run APP --reload` serves it. Hangman takes its words from whichever module
answers the `words.random` lookup; without the glossary (or another module answering
it) the page says there are no words yet, it does not fail. That is the subject of
[the next page](lookups.md).

## Where to go next

- [The manifest](manifest.md): every key of `module.yml`.
- [Lookups](lookups.md): cooperating with other modules without importing them.
- [Database](database.md): tables, migrations, translated text, search.
- [Templates and assets](templates-and-assets.md): pages, fragments, styles, translations.
- [Testing](testing.md): an application in a temporary workspace.
