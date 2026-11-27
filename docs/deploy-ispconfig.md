---
title: "Nest sites on a server with ISPConfig (nginx)"
description: "Run Nest sites as Docker images from Docker Hub, each a systemd service whose data live in a folder on the host, behind ISPConfig's nginx; Docker from the snap."
---
# Nest sites on a server with ISPConfig (nginx)

Every Nest application on the server runs the same way, as the Nest registry does: a
**Docker image** from Docker Hub, run by a **systemd service**, behind an **ISPConfig
website** (nginx, Let's Encrypt). Each application's repository has a `deploy/` folder
with what the server needs: the service, the nginx directives and a `DEPLOY.md` with its
own commands. Two small scripts in Nest's `deploy/site/` do the rest: `nest-secret-key` and
`nest-agent-tokens`.

![A Nest site on a server: nginx, the container, the data on the host](images/diagrams/deploy.svg)

**The data are never in the image.** An application's workspace (its SQLite databases, its
uploaded files, its settings, its backups, and a `.env` with its secrets) is a folder on the
host, `/var/snap/docker/common/nest/<app>`, mounted at `/data`, and owned by the ISPConfig
website's user: the container runs as that user. The container is thrown away at every
stop; a restart, a new image, going back to an older one, a crash or a reboot of the server
leaves the data where they are.

The folders are under `/var/snap/docker/common/` because Docker installed from the snap may
mount folders only there (and in `/home`). With Docker from the distribution's packages,
the services use `/usr/bin/docker` and `docker.service`, and the folders may be anywhere.

## What is where

| | |
|---|---|
| `<you>/nest-sites:<site>-latest` | a site's image (private repository, a tag per site); `miraur/nest-docsite`, `miraur/nest-keeper` (public) |
| `/etc/systemd/system/nest-<app>.service` | runs it (the repository's `deploy/nest-<app>.service`): the image, the port, the production settings |
| `/var/snap/docker/common/nest/<app>` | its workspace: `data/`, `media/`, `backups/`, and `.env` (`NEST_SECRET_KEY`, the agent's token) |

| application | port | domain |
|---|---|---|
| your sites | 8200, 8300, 8400, … (one each) | their own domains |
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
sites' images are private and share one repository, `<you>/nest-sites`, a tag per site
(`mysite-latest`, `mysite-0.1.0`, `othersite-latest`, ...): Docker Hub's free plan has one
private repository, and the layers the sites share (Python, Nest) are stored once. Create
it as private before the first push (a push creates a missing repository with the
account's default visibility). The server logs in once, **as root** (the services run as
root), with an access token that can read:

```sh
sudo docker login -u <you>
```

## An application, step by step

Each `deploy/DEPLOY.md` has the exact commands; for an application `A`:

1. **Its data folder.** A site brings its current workspace: stop it where it runs,
   `rsync -a --exclude run/ --exclude backups/ ~/.local/share/nest/A/ server:/tmp/A/`, then
   on the server move it to `/var/snap/docker/common/nest/A` and give it to the website's
   user (`chown -R webN:clientN`). The docsite and the keeper start with an empty folder.
2. **Its secret key.** `sudo sh nest-secret-key A`, in `/var/snap/docker/common/nest`:
   `NEST_SECRET_KEY` into the folder's `.env`, from the site's own `data/secret.key` (everyone
   stays signed in) or a new one.
3. **Its service.** `deploy/nest-A.service` into `/etc/systemd/system/`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now nest-A`. At each start it
   pulls the image, then runs it as the folder's owner with the folder mounted; the image
   migrates the database before it serves. `enable` starts it at every boot.
4. **Its website** in ISPConfig: domain, auto-subdomain `www.`, PHP disabled, Let's Encrypt
   on, the SEO redirect from `www.`; under **Options → nginx Directives**, `deploy/nginx.conf`
   (it proxies to `127.0.0.1:<port>`, lets uploads and live updates through).
5. **Its first account**, for an application that starts empty (the docsite, the keeper):
   right after the first start, `sudo docker exec -i nest-A nest auth create-user …`. A site
   that brought its data has its accounts already.
6. **Its backups**, one a night, by root's crontab:
   `30 3 * * * /snap/bin/docker exec nest-A nest backup /src/app --keep 14 >/dev/null`
   (`/src/nest/applications/A` for the docsite and the keeper). Copy them off the server too.

For the [keeper](operate/keeper.md) to watch the sites, `sudo sh nest-agent-tokens mysite
othersite …`: each site's container makes a token, its SHA-256 goes into the site's `.env`,
the site restarts, and the script prints the tokens for the keeper's **Watch a site**.
Until then a site's agent answers nobody.

## Updates and migrations

After a new image is pushed:

```sh
sudo docker exec nest-A nest backup /src/app     # a backup first
sudo systemctl restart nest-A                     # pulls the new image, migrates, serves
```

The image's entrypoint runs `nest db upgrade` (every module's migrations) before it serves;
a production site never migrates otherwise. To go back to an older version, name its tag in
the service (`Environment=IMAGE=<you>/nest-sites:mysite-0.1.0`), `daemon-reload`, restart;
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
DATA=/var/snap/docker/common/nest/mysite
PULL=<you>/nest-sites
TAG=mysite-latest
IMAGE=nest-mysite
MEMORY=1g
KEEP=14
```

```sh
sudo install -m 0755 nest-site /usr/local/bin/
sudo install -m 0644 nest-site*@.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo nest-site build mysite                         # pulls the image (PULL, TAG)
sudo systemctl enable --now nest-site@mysite nest-site-backup@mysite.timer
sudo nest-site upgrade mysite                       # later: pull, back up, restart, check, roll back
```

Without `PULL`, `nest-site build` builds the image on the server from the sources in
`/opt/nest/src` (`SRC`, `REPO`). Use one way per application, not both: they run the same
container name.

### Restarts, upgrades and restores from the keeper

The [keeper](operate/keeper.md) can restart, back up, upgrade, roll back and restore the
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
ALLOW=restart backup upgrade rollback restore
KEEPER_URL=https://keeper.example.org
```

`BIND` is `127.0.0.1` when the keeper runs on the host itself, and the Docker bridge's
address (`172.17.0.1`) when the keeper is a container. The helper refuses any public
address.

`restore` is allowed only when `ALLOW` names it (it replaces a site's data; the default
leaves it out). `KEEPER_URL` is the keeper's address: a restore of the keeper's copy of a
backup downloads it from there, through a one-time link. Without it, only the archives
already in the site's `backups/` can be restored. On the keeper's own server it may be the
keeper's local port (`http://127.0.0.1:8800`).

The keeper's environment then gets:

```text
NEST_KEEPER__KEEPER__HOST_URL=http://172.17.0.1:8090
NEST_KEEPER__KEEPER__HOST_TOKEN=nh_…
```

Each job and who asked for it is written to `/var/lib/nest-site/host-jobs.log` and to the
journal (`journalctl -u nest-host`). The helper drives `nest-site`, so it serves only the
applications run that way.

### Another server, behind its own Cloudflare tunnel

A second server runs `nest-site` and `nest-host` the same way, with `BIND=127.0.0.1` and
its `KEEPER_URL` set to the keeper's public address. The keeper reaches its helper through
that server's tunnel, and only with a Cloudflare Access service token:

1. In the server's tunnel, a public hostname for the helper: `host-2.example.org` →
   `http://localhost:8090` (cloudflared on the host; a cloudflared container needs the
   host's network to reach `localhost`).
2. In Cloudflare Zero Trust: **Access → Service Auth → Service Tokens**, a token for the
   keeper; then **Access → Applications**, a self-hosted application for
   `host-2.example.org` whose only policy is *Service Auth* with that token. Every other
   request is refused by Cloudflare before it reaches the server.
3. In the keeper: **Servers → Add a server**: the address `https://host-2.example.org`,
   the helper's `nh_…` token (`sudo nest-host token` on that server), and the service
   token's client ID and secret. The page asks the helper at once: its host's name, its
   sites, what it allows.
4. Each of that server's sites, on its **Change** page: the server, and its `nest-site`
   name.

The helper's own token is still required: Access keeps the address private, the token says
it is the keeper.

## Later: a database and file server

When a site outgrows SQLite (many writers at once: a game, not a blog), its `.env`
binds PostgreSQL and S3/MinIO instead (the lines are in each `.env` example); move its data
with `nest backup` and the database's own import. The images, the services and this
procedure stay the same.
