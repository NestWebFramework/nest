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

Workers: each is a process with its own Python, so pages are made in parallel; SQLite
reads well from several (WAL), and settings saved in one are seen by the others within
two seconds. A site serves several times the pages with as many workers as cores
(morlaca: about 60 category pages a second with one, 280 with four). An application
that pushes live updates between visitors (the game's realtime) needs one worker, or
a shared broker.

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
