# Deploying a Nest application

An application in its own repository (morlaca, transilpedia, voievodate…) runs in one
container image built from Nest's `deploy/Dockerfile`, with Nest checked out beside it.

## The image

```sh
cd ~/projects/morlaca
docker build -f ../nest/deploy/Dockerfile --build-context nest=../nest -t morlaca .
```

The application's `uv.lock` fixes every version. Inside, the application is `/src/app`
and its workspace `/data` (a volume): databases, stored files, settings. It runs as an
unprivileged user, with `NEST_ENV=production`, and checks its own `/healthz`.

`deploy/entrypoint.sh` migrates (`nest db upgrade`; production never migrates on its own)
and serves. Any nest command runs the same way:

```sh
docker compose run --rm app nest check /src/app
docker compose run --rm app nest auth create-user /src/app you@example.ro --role admin --password-stdin
```

## Its environment

| variable | |
|---|---|
| `NEST_SECRET_KEY` | required in production, 32+ characters: signs sessions and forms |
| `NEST_ALLOWED_HOSTS` | the hosts it answers (`morlaca.ro,www.morlaca.ro`); others get 400 |
| `NEST_TRUSTED_PROXIES` | whose `X-Forwarded-*` headers are believed (`*` only when the port is reachable from the proxy alone) |
| `PORT`, `NEST_WORKERS`, `NEST_LOG_LEVEL` | the port, processes, log level |

## Workers: nest serve

`nest serve APP` runs an application as gunicorn runs a Flask one: a master process
and its workers. The master makes the application once before it forks (migrations,
or in production the refusal to start behind them; its checks), then each worker
makes its own and serves it with uvicorn's asyncio server, synchronous handlers in a
pool of `threads`. gunicorn replaces a worker that dies or stays silent past
`timeout`, renews each after `max_requests` (with jitter), reloads them one by one
on `kill -HUP <master>` (no request lost), and stops them gracefully on SIGTERM.
`nest run` stays the development server (one process, reloading on changes).

```yaml
serve:                 # in the application's module.yml; all optional
  workers: auto        # processes: the CPUs this process may use     (NEST_WORKERS)
  threads: 16          # each worker's pool for synchronous handlers  (NEST_THREADS)
  timeout: 30          # seconds before a silent worker is replaced   (NEST_TIMEOUT)
  graceful_timeout: 20
  keepalive: 5
  max_requests: 5000   # requests before a worker is renewed          (NEST_MAX_REQUESTS)
  max_requests_jitter: 500
```

The environment overrides the manifest, the command line both (`nest serve . --workers
4 --threads 8`); `--dry-run` shows the plan and gunicorn's settings. Python runs one
thread at a time in a process, so pages are made in parallel by workers (about one
per core), while threads let a slow request not hold up the others; a few per
worker is plenty. Each worker uses about 85 MB.

What the workers must agree on, they share:

- **Settings** saved in one worker are seen by the others within two seconds; SQLite
  reads well from several (each worker lets one thread at a time into it).
- **Sign-in limits** are counted where every worker sees them: in the shared cache when
  the application binds one (redis), otherwise in the database (`auth_failure`,
  hashed keys, a row per failure, kept for the window). A guesser gets
  `login_attempts`, not that many times the workers.
- **A shared cache**: bind `nest.cache` to `redis` (Redis or Valkey) and every
  worker, on every machine, sees the same values. `cache-memory` keeps its values in
  each worker; with more than one, `nest serve` says so.
- **Live updates** (a forum post, a message, over SSE): bind `nest.pubsub` to `redis`
  and each worker relays what it publishes over one channel, so readers on every
  worker get it, once and in order. Without it, an event reaches only the visitors of
  the worker that made it, and `nest serve` says so. An event each worker makes for
  its own visitors (a clock) is published with `local=True` and not relayed.

  ```yaml
  bind:
    nest.cache: {providers: [redis]}
    nest.pubsub: {providers: [redis]}
  # NEST_<APP>__REDIS__URL=redis://:password@cache.lan:6379/0   (the environment)
  ```

- **Background tasks** run in every worker; `@host.background(single=True)` runs one
  in one worker of the workspace at a time (a file lock in `run/`), and another takes
  over within seconds if that worker stops. Several machines with their own
  workspaces each run their own.

### A game: the engine process

A module that keeps its state in its process says so (`one_process: true`, as Saga's
worlds do). With one worker nothing changes: that process does everything. With more,
`nest serve` starts one more process beside gunicorn's workers, the **engine**
(`nest engine`, `NEST_ROLE=engine`): the whole application with the worlds open and
ticking, listening on a Unix socket in the workspace (`run/engine.sock`). The workers
(`NEST_ROLE=web`) never open the worlds; they serve the site, the forum, letters,
accounts and assets themselves, and pass to the engine, streamed both ways:

- the routes of the game's packages (`/joc`, `/api/joc`) and their admin pages,
- an event stream that follows one of the game's topics (`saga.*`).

```
browser ──► workers (N)   /  /sfat  /scrisori  /cont  /admin  /assets   served here
              └─ /joc  /api/joc  /admin/saga …  saga.* streams ─► engine (1)
```

The engine answers only requests a worker signed with a token made from the
application's secret key, and takes the visitor's address from them. `nest serve`
waits for it to load the worlds before the workers start, starts it again if it stops
(the workers answer 503 "starting" meanwhile), and stops it after them with TERM, so it
writes the worlds first. `kill -HUP` reloads the workers only; the worlds keep ticking.
A worker names players (letters, the forum) by their characters as the engine's last
checkpoint wrote them. Bind `nest.pubsub` so a letter's live update reaches a game page
(served by the engine) as well.

To run the engine as a service of its own (another container), start `nest engine APP
--host 0.0.0.0 --port 8001` there and give the workers `NEST_ENGINE_URL=http://engine:8001`;
both need the same workspace secret key.

Measured with morlaca (4 workers x 8 threads): about 280 category pages a second
and 320 feeds, a worker killed is replaced in seconds, and 3,000 requests made
during a HUP reload all succeeded.

Secrets live in the environment or the workspace `.env`, never in `module.yml`.

## Is it ready?

`nest check APP` lists what production needs: production mode, the key, the hosts, the
public address (`content.site_url`), a writable workspace and free disk, the SQLite
databases' journal and integrity, an administrator, a recent backup. It exits 1 on a failure.

## Backups

`nest backup APP [--to DIR] [--keep N]` writes the workspace into one `.tar.gz`: every
SQLite database copied while the site runs (SQLite's online backup), the stored files and
the settings. It leaves out `.env` (secrets stay with the server) and the pictures media
makes at other widths (made again when asked for). A database on a server (Postgres,
MariaDB) is backed up with its own tools.

`nest restore APP ARCHIVE [--force]` puts one back, the application stopped. The same
pair moves a site: back it up where it was imported, restore it on the server.

## In front: Caddy

An application's `deploy/compose.yml` runs the site, a nightly backup (the last 14 kept)
and Caddy, which gets and renews the HTTPS certificate. Copy the backups off the server.

## Caching

Versioned assets (`/assets/<module>/<file>?v=…`) are kept a year (`immutable`), stored
files a week, sized pictures are made once. Pages are not cached for visitors: each one
carries the visitor's form token, and rendering one is a few milliseconds.
