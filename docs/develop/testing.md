---
title: "Testing modules and applications"
description: "Test a Nest module or application with pytest: create_app in a temporary workspace, TestClient, CSRF and signing in, fixture applications, manifest and contract tests, and ruff."
---

# Testing modules and applications

A Nest application is made by one function, `create_app(app_dir, environ=...)`, from its
folder and an environment. A test makes it in a temporary workspace, drives it with
FastAPI's `TestClient`, and throws it away: no server, no shared database, no state left
between tests.

## Running the suite

In the Nest repository:

```sh
uv run pytest                          # packages/nest-core/tests and tests/
uv run pytest tests/test_geo.py -q     # one file
uv run pytest -k hangman               # tests whose name matches
uv run ruff check .                    # lint: errors, imports, bugbear, pyupgrade, simplify
uv run ruff format .                   # the formatter owns line length (100)
```

The root `pyproject.toml` sets `testpaths = ["packages/nest-core/tests", "tests"]` and
ruff's rules (`E`, `F`, `I`, `B`, `UP`, `SIM`). FastAPI dependencies used as argument
defaults (`bound(Database)`, `Depends(...)`) are declared immutable for bugbear, so they
pass `B008`.

## An application in a temporary workspace

Everything an application keeps at run time (its SQLite database, settings, signing key,
media) lives in its workspace. Point `NEST_APP_WORKSPACE` at pytest's `tmp_path` and each
test gets a fresh one:

```python
import textwrap

from fastapi.testclient import TestClient

from nest import create_app

APP = """
module: {name: harta, id: test.app.harta, type: application, version: 0.1.0}
application: {title: Hartă, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: geo, route: /aproape}
  - {name: maps, route: /harti}
  - {name: admin, route: /admin}
  - {name: auth, route: /cont}
bind:
  nest.db: {providers: [db-sqlite]}
"""


def test_the_near_me_page_gathers_every_module(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        page = c.get("/aproape/")
        assert page.status_code == 200
        assert "geolocation=(self)" in page.headers["permissions-policy"]
        assert "geolocation=()" in c.get("/harti/").headers["permissions-policy"]
        assert c.get("/aproape/places?lat=999&lon=0").status_code == 400
```

The application's manifest is written in the test, with only the modules it needs.
`environ` replaces the process environment for `create_app`, so a developer's own
`NEST_*` variables never leak into a test. Use `with TestClient(app) as c:` so the
application's startup and shutdown run (background tasks, hooks).

A module that should degrade without a partner gets a test of its own. Hangman, with no
module answering `words.random`:

```python
def test_hangman_without_words_says_so(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(
        "module: {name: joc, id: test.app.joc, type: application, version: 0.1.0}\n"
        "application: {title: Joc, port: 8000, theme: base, languages: [ro]}\n"
        "modules:\n  - {name: hangman, route: /}\n",
        encoding="utf-8",
    )
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        r = c.get("/")
        assert r.status_code == 200 and "Încă nu sunt cuvinte" in r.text
```

## Fixture applications

When several tests share a larger application, keep it as a folder in
`tests/fixtures/` (the glossary's tests use `tests/fixtures/glossary-app/module.yml`,
the glossary as a dictionary site mounts it) and make it in a fixture. Data is put in
through the module's own service functions, with the bound providers:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_glossary import importer, service

from nest import create_app

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tests" / "fixtures" / "glossary-app"
EXAMPLE = ROOT / "tests" / "fixtures" / "glossword_example.txt"


@pytest.fixture
def site(tmp_path):
    app = create_app(APP, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    nest = app.state.nest
    db, search = nest.bindings.get("nest.db"), nest.bindings.get("nest.search")
    urls = nest.module_state["glossary"]["urls"]
    moldova = service.ensure_dictionary(db, "Graiul moldovenesc")
    importer.import_terms(db, search, moldova, importer.read_glossword(EXAMPLE.read_text()), urls.term)
    with TestClient(app) as c:
        c.db, c.search = db, search
        yield c
```

`app.state.nest` is the running application: `bindings.get("nest.db")` the database,
`module_state["<module>"]` a module's state, `lookup(...)` and `gather(...)` the modules'
answers. Tests may read them; module code may not read another module's state.

## CSRF in tests

Every POST to a module's routes needs the CSRF token (see [security](security.md)). The
`nest_csrf` cookie is set by any response except a reader's HTML page that holds no form,
so a test first asks for something that sets it (`/healthz` does), then sends the token
back as a form field or a header:

```python
def token(c: TestClient) -> str:
    c.get("/healthz")
    return c.cookies["nest_csrf"]


r = c.post(
    "/spanzuratoare/guess",
    data={"csrf_token": token(c), "letter": "A"},
    headers={"HX-Request": "true"},  # the htmx fragment, not a redirect
)
```

```python
def csrf(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies["nest_csrf"]}
```

Asserting the refusal is a test worth having for any form a module adds: a POST without
the token answers 403.

## Signing in

Create the user with the auth module's `create_user`, with the roles the page asks for,
then sign in through the real form:

```python
from nest_auth.sessions import create_user

PASSWORD = "correct horse battery"


def sign_in(c: TestClient, email: str, roles: tuple[str, ...]) -> None:
    create_user(c.db, email, PASSWORD, roles=roles)
    c.get("/healthz")
    r = c.post(
        "/cont/login",
        data={"csrf_token": c.cookies["nest_csrf"], "email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_a_reader_cannot_edit(site):
    sign_in(site, "reader@example.ro", ())
    assert site.get("/graiul-moldovenesc/new").status_code == 403


def test_an_editor_adds_a_term(site):
    sign_in(site, "ed@example.ro", ("editor",))
    assert "Termen nou" in site.get("/graiul-moldovenesc").text
    headers = {**csrf(site), "HX-Request": "true"}
    r = site.post("/graiul-moldovenesc/new", data={"word": "", "definition": "x"}, headers=headers)
    assert "Câmpul este obligatoriu." in r.text  # the form again, with its error
```

The path is the auth module's route in the fixture application (`/cont` here). The
client keeps the session cookie for the rest of the test.

## Testing manifests and the plan

Nest's own tests check manifests and plans without starting anything:

```python
from nest.contract import load_contracts

# parse() and base() are the test file's helpers: a manifest from a dict, and a module's
# identity with the given sections added


def test_core_contract_rules():
    contract = load_contracts()
    assert contract.validate(parse(base(main="x"))) == []
    problems = contract.validate(parse(base()))
    assert problems == ["a module must declare 'main'"]
```

`nest.resolve.plan(app_entry, Catalog.discover(root), load_contracts())` makes an
application's plan, or raises `PlanError` with every problem at once; the core tests
(`packages/nest-core/tests/test_resolve.py`) build small applications with local modules
in `tmp_path` to test ordering and errors.

## Contract tests in an application

An application kept in its own repository depends on Nest's
packages twice: in `module.yml`'s `deps` (by ecosystem, with version ranges) and in
`pyproject.toml`'s dependencies. A contract test keeps them in step, in the
application's `tests/test_contract.py`:

```python
from nest.catalog import Catalog, Entry
from nest.contract import load_contracts
from nest.manifest import load_manifest
from nest.resolve import ecosystem_of, plan
from paths import APPLICATION  # the repository's root: the application's folder


def test_every_dependency_names_its_ecosystem_and_version():
    manifest = load_manifest(APPLICATION)
    catalog, contract = Catalog.discover(APPLICATION), load_contracts()
    for name, spec in manifest.deps.items():
        entry, _ = catalog.find(name)
        assert entry is not None, name
        assert spec, f"{name} has no version range"
        assert manifest.dep_ecosystems[name] == ecosystem_of(entry, contract), name
    plan(Entry(manifest=manifest, source="application"), catalog, contract)  # it runs by them
```

A second test compares each dependency's range with what `pyproject.toml` asks for, and
fails on a package one lists and the other does not. Beside it, a site test makes the
application itself, loads a small sample of real data, and asks for its main pages:

```python
def test_pages(tmp_path):
    app = create_app(APPLICATION, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        for path in ("/", "/cfr/", "/in-apropiere/"):
            assert c.get(path).status_code == 200, path
```

## What to test in a module

- its pages answer, in each language the module ships a catalog for;
- its forms refuse a missing CSRF token, and its admin pages refuse a visitor without the
  role;
- the lookups it answers return what their askers expect, and it degrades when a lookup it
  asks has no answer;
- its migrations run from nothing (`create_app` in a fresh workspace runs them, as
  `NEST_MIGRATE=auto` is the default outside production);
- `uv run nest validate --strict` passes for it.
