---
title: "Lookups: modules that cooperate without importing each other"
description: "host.answer, host.lookup, host.gather and nest.answered; fallbacks and their priorities; shortcodes; background tasks; the lookups Nest's modules answer."
---

# Lookups: modules that cooperate without importing each other

Modules are reused across applications in any combination: a site may have the glossary
and hangman, another hangman alone, a third the glossary and comments. If hangman
imported the glossary, it could not run without it, and an upgrade of one could break
the other. So modules talk through the application instead: one **answers** a named
question, another **asks** it, and neither imports the other.

`nest validate --strict` enforces the rule: importing a package one does not depend on,
or reading another module's state, is reported.

## The four calls

| Call | What it does |
|---|---|
| `host.answer(name, fn)` | registers `fn(key)` as an answer to `name` |
| `host.lookup(name, key=None)` | asks every module that answers `name`, in start order; the first answer that is not `None` wins |
| `host.gather(name, key=None)` | every module's answer that is not `None`, as a list; an answer that raises is logged and skipped |
| `nest.answered(name)` | whether any module answers `name`, on the application object (`request.app.state.nest`) |

The same `lookup`, `gather` and `answered` are on `request.app.state.nest`, for handlers.
A name is a dotted string by convention: the module that defines the question first
(`seo.urls`, `words.random`, `admin.waiting`). The key and the answer are plain data:
dicts, lists, strings. A module that answers a question returns `None` for what it does
not know, so the next one may answer.

## One answer: lookup

Hangman needs a word and takes it from whichever module answers `words.random`. The
glossary answers it:

```python
def setup(host: ModuleHost) -> None:
    db = host.bound("nest.db")

    def random_word(options: object) -> dict | None:
        """A published word at random, with its first definition as a clue."""
        from nest_glossary import service

        o = options if isinstance(options, dict) else {}
        t, d = service.random_term(db, int(o.get("min", 4)), int(o.get("max", 14)))
        return _word(t, d)  # {"ref", "word", "clue", "source", "url"} or None

    host.answer("words.random", random_word)
    host.answer("words.by_ref", word_by_ref)
```

and hangman asks, keeping `host.lookup` in its state for its handlers:

```python
def _new_word(state: dict[str, Any]) -> dict | None:
    return state["lookup"](
        "words.random", {"min": state["min_letters"], "max": state["max_letters"]}
    )
```

Without a module answering, the lookup returns `None` and hangman says there are no
words yet. A module that would rather use another's service when it is there, and its
own way otherwise, asks `nest.answered` first. The trains module puts a map on a station
page only when the maps module is in the application:

```python
nest = request.app.state.nest
station_map = None
if st.latitude and st.longitude and nest.answered("maps.element"):
    station_map = nest.lookup(
        "maps.element",
        {
            "request": request,
            "data": f"{_base(request)}/gara/{st.slug}/harta.geojson",
            "lat": st.latitude,
            "lng": st.longitude,
            "zoom": 14,
            "title": st.name,
            "fit": False,
        },
    )
```

## Every answer: gather

`gather` collects from all. The seo module builds the sitemap from every module's
`seo.urls`; the geo module's near-me page shows what every module has near a point:

```python
def groups(request: Request, lat: float, lon: float) -> list[dict[str, Any]]:
    state = module_state(request, "geo")
    q = {"lat": lat, "lon": lon, "km": state["radius_km"], "limit": state["limit"]}
    return [
        answer
        for answer in state["gather"]("geo.near", q)
        if isinstance(answer, dict) and answer.get("places")
    ]
```

A module with places takes part by answering:

```python
host.answer("geo.near", lambda q: {"title": "Stations", "places": [
    {"title": ..., "url": ..., "km": ..., "note": ...}, ...]})
```

`gather` is also how a module tells the others something happened: the translations
module gathers `translations.changed` after a save, and the content module answers it by
refreshing its addresses and search index. Nobody has to know who listens.

## The lookups in Nest's modules

| Name | Answered by | Asked by | Key → answer |
|---|---|---|---|
| `seo.urls` | glossary, hangman, content, gallery, maps, trains, docs | seo (gather) | none → a list of `{path, title, kind, group, subject, lastmod, images, edit}` |
| `seo.text` | glossary, hangman, content, trains | seo (lookup) | a subject (`"glossary.term:12"`) → `{lead, text, context}`, the page's words for SEO proposals |
| `seo.site_url` | seo | the host (prefixed language URLs) | none → the site's public address |
| `words.random`, `words.by_ref` | glossary | hangman | `{min, max}` or a reference → `{ref, word, clue, source, url}` |
| `geo.near` | maps, trains | geo (gather) | `{lat, lon, km, limit}` → `{title, places: [...]}` |
| `maps.element` | maps | trains | `{request, data, lat, lng, zoom, title, fit}` → a map's HTML |
| `map.points` | content | maps (gather) | `{locale}` → places to show on a map |
| `admin.waiting` | glossary, comments | admin (gather) | none → `{module: count}` of what waits for a moderator |
| `translations.save`, `translations.states`, `translations.check`, `translations.kinds` | translations | content, gallery | the editors' side of translated text |
| `translations.changed` | content | translations (gather) | `{subject, ids, locales}`: a translation was written |
| `redirects.request` | redirects | glossary | a request → a redirect response, or `None` |
| `redirects.moved` | redirects | content | `{source, target, note}`: a page moved, add a redirect |
| `glossary.legacy_subject` | glossary | comments (Glossword import) | an old Glossword address → `"glossary.term:<id>"` |
| `wordpress.post` | content | comments (WordPress import) | an old WordPress post id → its entry |
| `module.removed` | seo, comments | the host (gather), on uninstall | a module's name: forget what was kept about it |

`module.removed` is gathered by Nest itself when an administrator uninstalls a module:
seo forgets what was said about its pages, comments the threads on its records.

## Fallbacks: paths a module stores

A module that serves addresses it stores rather than declares (a CMS page at
`/history/the-church/`, an old address to redirect) cannot add a catch-all route: it
would shadow every module mounted after it. Instead it registers a fallback, asked only
for a GET (or HEAD) that no route matched:

```python
def answer(request: Request) -> Response | None:
    db = request.app.state.nest.bindings.get("nest.db")
    r = service.find(db, request.url.path, request.url.query)
    if r is None:
        return None              # not mine: the next fallback, then 404
    service.hit(db, r.id)
    if r.status == 410:
        raise HTTPException(410)
    return RedirectResponse(r.target, status_code=r.status)


def setup(host: ModuleHost) -> None:
    host.answer("redirects.request", answer)
    host.fallback(answer, priority=-10)
```

Fallbacks are asked by `priority`, highest first, then in start order. The content
module uses `priority=10` and redirects `-10`, so a page that exists always wins over a
redirect pointing away from it. A fallback returns a response, or `None` to pass; raising
an `HTTPException` ends the search with that status. A blocking (plain `def`) fallback
runs in the thread pool.

## Shortcodes

Rich text may hold `[name attr="value"]`, answered by whichever module registered the
name. The gallery gives the content module's pages `[album slug="..."]` without either
importing the other:

```python
host.shortcode("album", lambda attrs, ctx: answer(by_attrs(attrs), ctx))
```

A handler receives the attributes as a dict of strings and a context (the request, or
what the module expanding the text passes), and returns safe HTML: it escapes what it
inserts. A handler that raises renders nothing, a shortcode nobody registered stays as
written, and a name is registered by one module only. Expansion happens only in text,
never inside a tag.

The maps module answers `[map]` and `[map slug="sat"]`; the content module answers
`[youtube id="..."]` and `[catlist id=3]`. A template expands text with the
`shortcodes()` global: `{{ shortcodes('[map]') }}`.

## Background tasks

A task that runs from startup until shutdown is an `async` function registered with
`@host.background`:

```python
@host.background(single=True)
async def timetable_sync() -> None:
    from nest_trains.sync import sync

    await asyncio.sleep(30)  # let the site start first
    while True:
        hours = max(1, int(host.settings.get("sync_hours") or 24))
        if host.settings.get("sync"):
            db = host.bound("nest.db")
            try:
                # host.workspace needs `requires: {host: [workspace]}` in module.yml
                await run_in_threadpool(sync, db, host.workspace / "data" / "trains-sources")
            except Exception:
                log.exception("timetable sync failed")
        await asyncio.sleep(hours * 3600)
```

Under `nest serve` each worker runs a plain `@host.background` task.
`@host.background(single=True)` runs it in one worker of the workspace at a time, holding
a lock file in the workspace's `run/` folder: the others wait, and one takes over if that
worker stops. Use it for anything that must not run twice at once: a nightly clean-up, a
feed fetched every hour. Blocking work goes to `run_in_threadpool`, so the event loop
keeps serving requests. Tasks are cancelled at shutdown.

For one-off work at start and stop, `host.on_startup(fn)` and `host.on_shutdown(fn)` take
plain or `async` functions.
