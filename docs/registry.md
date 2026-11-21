# The Nest registry: registry.nest-framework.org

Nest packages (modules, themes, providers, interfaces, an engine and its subsystems) are
Python packages that carry their manifest. The registry keeps them, and is two things on
one store:

- **a Python package index** (the simple API: PEP 503 pages, PEP 691 JSON) at `/simple/`,
  so `uv` installs a Nest package as any Python one, each file's sha256 pinned in
  `uv.lock`;
- **a catalog** of what each package is for Nest, read from its `module.yml` when it is
  published (type, ecosystem, the nest-core versions it works with, what it needs and
  uses, a theme's colours), at `/` to browse and `/api/v1/` for `nest packages` and the
  keeper.

It is a Nest application (`applications/registry`, the `registry` module): anyone can run
their own; registry.nest-framework.org is Nest's.

## A package that can be published

- It carries its manifest: `src/<package>/module.yml`, so the wheel has it (Nest's own
  packages all do; `nest new module` makes them so).
- It says which nest-core versions it works with: `nest: ">=0.2,<1"`. An application
  whose nest-core is outside the range does not start with it, and `nest packages`
  refuses to install it.
- It keeps its type's contract and its boundaries (`nest validate --strict`).
- Applications are deployed, not published.

## Publishing

```
nest login --registry https://registry.nest-framework.org --token nrt_…   # once
nest publish modules/forum               # check, build (uv), upload the wheel and sdist
nest publish modules/forum --dry-run     # check and build only
nest publish --all                       # every package of this Nest checkout the registry lacks
```

`--all` skips every version the registry has, so it publishes what changed; nest-core,
the host, goes to the index only (it has no manifest: it is no package to add, but an
application installs it from here like the rest; the registry's `index_only` setting
names it, and only administrators publish it). Nest's repository runs `nest publish --all`
on every version tag (`.github/workflows/publish.yml`, the token in the repository secret
`NEST_REGISTRY_TOKEN`), after its tests pass.

A package page tells what the package's author says it is: the opening comment of its
`module.yml`, as prose. A theme shows its colours (its `preview:`), or its picture when its
manifest names one inside the package (`screenshot: static/screenshot.png`).

The token is made on the registry's **Tokens** page (signed in), shown once, kept there
as a hash, revocable; `nest login` keeps it in `~/.config/nest/credentials.yml`, readable
by you only. In CI, set `NEST_REGISTRY_TOKEN` instead. A published file is never replaced:
a fix is a new version.

## Who may publish what

| Who | May |
|---|---|
| anyone, no account | browse the catalog, install every public package |
| an account | sign in; with `publishers: anyone`, publish too |
| a **publisher** (the `publisher` role, given by an administrator in Accounts) | make tokens; publish new packages in a namespace that is theirs; publish versions of packages they own or maintain |
| a package's **owner** (the account that first published it) | publish its versions; choose its **maintainers** (on its page) |
| a **maintainer** | publish versions of that package (not choose maintainers) |
| an **administrator** | all of it, and the official namespace `nest.` |

- **Who may publish at all** is the registry's `publishers` setting: `approved` (the
  default: only publishers and administrators) or `anyone`. registry.nest-framework.org
  lets anyone make an account and approves publishers.
- **Namespaces**: a package id's first segment (`acme` in `acme.module.widgets`) is owned
  by the first account to publish in it; nobody else starts a package in it. `nest` is
  the administrators'.
- **Names**: a package's name and its distribution's name belong to the account that
  first published them.
- **Tokens** act for their account only while it is active: a disabled account's
  tokens stop working, and a revoked token at once.

## Signatures

```
nest keygen --register        # an Ed25519 key: the private half yours only, the public one to the registry
nest publish modules/forum    # each file signed: its name and its sha256
nest trust add forum <key>    # this machine installs forum only signed by that key ("*": every package)
nest trust list
```

The registry takes a signature only from a key the publishing account registered (the
Tokens page, or `--register`), and refuses a signature that does not hold; with
`require_signatures` it takes signed files only. A package page shows each file's signer.
When installing, a package with pinned keys is refused unless its file is signed by one of
them, before anything changes; and the sha256 `uv.lock` pins must be the signed one. In CI,
`NEST_SIGNING_KEY` holds the private key's PEM.

## Private packages, withdrawn versions

- `nest publish ... --private` (a new package), or `nest visibility forum private|public`,
  or its page: a private package is its owner's, its maintainers' and the administrators'.
  To anyone else it does not exist (the same "not found" as a package that is not there).
  `uv` signs in with your token (`nest packages` gives it as `UV_INDEX_NEST_USERNAME` /
  `UV_INDEX_NEST_PASSWORD`), so the token is never written in `pyproject.toml` or `uv.lock`.
- `nest yank forum 0.1.0 --reason "..."` (or its page): installers pass a withdrawn version
  by unless it is asked for exactly, so an application pinned to it keeps working; the
  catalog offers the newest version not withdrawn. `nest unyank` brings it back. The owner's
  or an administrator's.

## Running it

See `docs/registry-deploy.md`: one Docker image, a systemd service behind nginx
(ISPConfig), SQLite and a volume, or PostgreSQL and S3/MinIO chosen in its environment
(`NEST_BIND__NEST_DB=db-postgres`, `NEST_BIND__NEST_STORAGE=storage-s3`: an application's
manifest lists such `alternatives:` beside its providers).

## Installing from it

```
nest packages APP list --remote          # what the registry offers
nest packages APP add forum --remote     # into pyproject.toml and module.yml, then uv sync
```

The registry is `$NEST_REGISTRY_URL`, else the one `nest login` saved, else
https://registry.nest-framework.org. It offers each package's newest release **that works
with the application's nest-core** (`/api/v1/packages?nest=<version>`); one with none is
not offered.

Installing adds the package, and the registry's index named `nest`, listed before PyPI.
uv takes a package from the first index that has it (its default, *first-index*), so a
Nest package, its Nest dependencies and nest-core come from the registry only, never from
a package of the same name on PyPI; what the registry does not have (fastapi, sqlalchemy)
comes from PyPI. A path source to a Nest checkout the application had for the package is
replaced. A provider brings the interfaces it implements (redis: cache and pubsub), since
the application binds them. `uv.lock` pins each file's sha256, the one the registry shows.
The package arrives *installed, not used*: the application's administrator enables it
(Modules), or chooses it (Themes), or binds it (a provider).

An application can be made of packages from the registry alone, with no Nest checkout:
its `pyproject.toml` asks for `nest-core` with the `nest` index, then `nest packages . add
<name> --remote` adds the rest.

**Searching**: the keeper's Packages page searches the registry and installs from it (the
server's administrator); an application's admin panel (Modules) searches it too, read-only:
it shows what works with the application and the command its server's administrator runs.

By hand, as any Python package: `uv add nest-forum --index nest=https://registry.nest-framework.org/simple/`.

## Running one

```
nest run applications/registry                      # or nest serve
nest auth create-user applications/registry you@example.org --role admin --password-stdin
nest registry token applications/registry you@example.org   # a token from the command line
```

SQLite and local files to begin with; PostgreSQL and MinIO by changing the bindings.
