---
title: "Nest sites on a server with ISPConfig (nginx)"
description: "Run Nest sites as Docker images from Docker Hub, each a systemd service whose data live in a folder on the host, behind ISPConfig's nginx."
---
# Nest sites on a server with ISPConfig (nginx)

Every Nest application on the server runs the same way, as the Nest registry does: a
**Docker image** from Docker Hub, run by a **systemd service**, behind an **ISPConfig
website** (nginx, Let's Encrypt). Each application's repository has a `deploy/` folder
with what the server needs: the service, an `.env` example, the nginx directives and a
`DEPLOY.md` with its own commands.

![A Nest site on a server: nginx, the container, the data on the host](images/diagrams/deploy.svg)

**The data are never in the image.** An application's workspace (its SQLite databases, its
uploaded files, its settings, its backups) is a folder on the host, `/srv/nest/<app>`,
mounted at `/data`. The container is thrown away at every stop; a restart, a new image,
going back to an older one or a crash leaves the data where they are. The secrets are in
`/etc/nest/<app>.env` (root only), never in an image, a repository or a backup.

## What is where

| | |
|---|---|
| `miraur/nest-sites:<site>-latest` | a site's image (private repository, a tag per site); `miraur/nest-docsite`, `miraur/nest-keeper` (public) |
| `/etc/systemd/system/nest-<app>.service` | runs it (the repository's `deploy/nest-<app>.service`) |
| `/etc/nest/<app>.env` | its secrets and production settings (`deploy/<app>.env.example`) |
| `/srv/nest/<app>` | its workspace: `data/`, `media/`, `backups/`, owned by uid 10001, the image's user |

| application | port | domain |
|---|---|---|
| regionalisme | 8200 | regionalisme.ro |
| morlaca | 8300 | morlaca.ro |
| transilpedia | 8310 | transilpedia.ro |
| gari | 8400 | gari.ro |
| voievodate (later) | 8500 | voievodate.ro |
| registry | 8600 | registry.nest-framework.org (its own guide: [registry-deploy.md](registry-deploy.md)) |
| docsite | 8700 | nest-framework.org |
| keeper | 8800 | your own domain |

## The images

Built and pushed from a development machine, from Nest's repository, out of committed code:

```sh
deploy/site/nest-images build            # all six: the four sites, docsite, keeper
deploy/site/nest-images push             # refused for an image built from uncommitted code
```

Each image is tagged with its version, the commits it was made from, and `latest`. Nest's
own images (`nest-docsite`, `nest-keeper`) are public, each in its own repository. The
sites' images are private and share one repository, `miraur/nest-sites`, a tag per site
(`gari-latest`, `gari-0.1.0`, `morlaca-latest`, ...): Docker Hub's free plan has one
private repository, and the layers the sites share (Python, Nest) are stored once. Create
it as private before the first push (a push creates a missing repository with the
account's default visibility). The server logs in once, with a read-only access token:

```sh
sudo docker login -u miraur
```

## An application, step by step

Each `deploy/DEPLOY.md` has the exact commands; for an application `A`:

1. **Its data folder.** Bring the current workspace (stop it where it runs, then
   `rsync -a --exclude run/ --exclude backups/ ~/.local/share/nest/A/ server:/tmp/A-data/`,
   move it to `/srv/nest/A`, `chown -R 10001:10001`), or start with an empty one.
2. **Its environment.** `scp deploy/A.env.example deploy/nest-A.service server:/tmp/`, then
   `/etc/nest/A.env` from the example (`chmod 600`). `NEST_SECRET_KEY` is the workspace's
   `data/secret.key` when its data came along: everyone stays signed in. One `KEY=VALUE`
   per line, nothing after the value.
3. **Its service.** `/etc/systemd/system/nest-A.service`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now nest-A`. At each start it
   pulls the image, then runs it with the data folder mounted; the image migrates the
   database before it serves.
4. **Its website** in ISPConfig: domain, auto-subdomain `www.`, PHP disabled, Let's Encrypt
   on, the SEO redirect from `www.`; under **Options → nginx Directives**, `deploy/nginx.conf`
   (it proxies to `127.0.0.1:<port>`, lets uploads and live updates through).
5. **Its backups**, one a night, by root's crontab:
   `30 3 * * * docker exec nest-A nest backup /src/app --keep 14 >/dev/null`
   (`/src/nest/applications/A` for the docsite and the keeper). Copy them off the server too.

For the [keeper](operate/keeper.md) to watch a site, give its agent a token:
`nest agent token A --control` prints the token for the keeper and a
`NEST_A__AGENT__CONTROL_TOKEN=sha256:…` line for `/etc/nest/A.env`, then
`sudo systemctl restart nest-A`. Until then the agent answers nobody.

## Updates and migrations

After a new image is pushed:

```sh
sudo docker exec nest-A nest backup /src/app     # a backup first
sudo systemctl restart nest-A                     # pulls the new image, migrates, serves
```

The image's entrypoint runs `nest db upgrade` (every module's migrations) before it serves;
a production site never migrates otherwise. To go back to an older version, name its tag in
the service (`Environment=IMAGE=miraur/nest-sites:gari-0.1.0`), `daemon-reload`, restart;
if the newer one had migrated the database, restore the backup made before it
(`nest restore`, the site stopped). Each `DEPLOY.md` has the commands.

## Day to day

```sh
sudo journalctl -u nest-A -f                          # its log
sudo systemctl restart nest-A                         # restart (the data stay)
sudo docker exec nest-A nest check /src/app           # what production asks of it
sudo docker exec nest-A nest db status /src/app       # its migrations
sudo docker exec -it nest-A nest <command> /src/app … # any nest command, in the running site
```

## Another way: nest-site

Nest's `deploy/site/` also has `nest-site`, a tool that does upgrades in one command: pull
or build the image, back up, restart, wait until it answers healthy, and **roll back by
itself** (the image before and the data before) when it does not. It runs the same image
with the same data folder, through its own units (`nest-site@<app>.service` and a nightly
`nest-site-backup@<app>.timer`), and reads `/etc/nest/<app>.conf`:

```text
PORT=8400
DATA=/srv/nest/gari
PULL=miraur/nest-sites
TAG=gari-latest
IMAGE=nest-gari
MEMORY=1g
KEEP=14
```

```sh
sudo install -m 0755 nest-site /usr/local/bin/
sudo install -m 0644 nest-site*@.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo nest-site build gari                         # pulls the image (PULL, TAG)
sudo systemctl enable --now nest-site@gari nest-site-backup@gari.timer
sudo nest-site upgrade gari                       # later: pull, back up, restart, check, roll back
```

Without `PULL`, `nest-site build` builds the image on the server from the sources in
`/opt/nest/src` (`SRC`, `REPO`). Use one way per application, not both: they run the same
container name.

### Restarts and upgrades from the keeper

The [keeper](operate/keeper.md) can restart, back up, upgrade and roll back the
applications `nest-site` runs, through the host helper:

```sh
sudo install -m 0755 nest-host /usr/local/bin/
sudo nest-host token        # a token for the keeper, and the line for host.conf
sudo editor /etc/nest/host.conf
sudo install -m 0644 nest-host.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nest-host
```

`/etc/nest/host.conf` (one `KEY=VALUE` per line, no comment after a value):

```text
TOKEN_SHA256=sha256:…
BIND=172.17.0.1
PORT=8090
ALLOW=restart backup upgrade rollback
```

`BIND` is `127.0.0.1` when the keeper runs on the host itself, and the Docker bridge's
address (`172.17.0.1`) when the keeper is a container. The helper refuses any public
address. The keeper's environment then gets:

```text
NEST_KEEPER__KEEPER__HOST_URL=http://172.17.0.1:8090
NEST_KEEPER__KEEPER__HOST_TOKEN=nh_…
```

Each job and who asked for it is written to `/var/lib/nest-site/host-jobs.log` and to the
journal (`journalctl -u nest-host`). The helper drives `nest-site`, so it serves only the
applications run that way.

## Later: a database and file server

When a site outgrows SQLite (many writers at once: a game, not a dictionary), its `.env`
binds PostgreSQL and S3/MinIO instead (the lines are in each `.env` example); move its data
with `nest backup` and the database's own import. The images, the services and this
procedure stay the same.
