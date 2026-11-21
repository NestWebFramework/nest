# Running the keeper

The keeper runs on the server as the Nest registry does: one Docker image from Docker Hub, run by
a systemd service, behind an ISPConfig website (nginx, Let's Encrypt). What differs from the
registry is where its data are: **a plain folder on the server**, mounted into the container.
Restarting, updating or replacing the container leaves the folder as it is, and so it
survives a reboot of the server too.

| | |
|---|---|
| image | `miraur/nest-keeper:latest` (public) |
| service | `nest-keeper`: `applications/keeper/deploy/nest-keeper.service` |
| data | `/var/snap/docker/common/nest/keeper`, owned by the website's user (the container runs as that user) |
| port | `127.0.0.1:8800` (loopback only: nginx faces the network) |
| domain | `keeper.example.org` |

The data folder holds everything that changes: the database (`data/app.db`, `data/search.db`),
the uploaded files (`media/`), the settings made in the admin panel (`data/settings.conf`),
the backups (`backups/`), and a `.env` with its secrets (`NEST_SECRET_KEY`, the agent's
token). It is under `/var/snap/docker/common/` because Docker installed from the snap may
mount folders only there (and in `/home`).

## 1. The data folder, empty

A fresh keeper starts empty: you add the sites to watch in its pages.
Make the folder and give it to the website's user (ISPConfig's `webN` and `clientN` of
`keeper.example.org`: `stat -c %U:%G /var/www/keeper.example.org/web`):

```sh
sudo mkdir -p /var/snap/docker/common/nest/keeper
sudo chown webN:clientN /var/snap/docker/common/nest/keeper
```

## 2. The secret key

In production a site needs `NEST_SECRET_KEY`; it reads it from the `.env` in its data folder.
Nest's `deploy/site/nest-secret-key` writes it there: the site's own key from development
(`data/secret.key`, so everyone stays signed in), or a new one; a key already set is left
alone. Copy the script to the server once, then:

```sh
scp deploy/site/nest-secret-key deploy/site/nest-agent-tokens server:/tmp/      # from your machine
```
```sh
cd /var/snap/docker/common/nest && sudo sh /tmp/nest-secret-key keeper
```

## 3. The service

`applications/keeper/deploy/nest-keeper.service` (this repository) goes to `/etc/systemd/system/`. It pulls the image at each start
(the cached one if Docker Hub cannot be reached), runs the container as the data folder's
owner with the folder mounted at `/data`, and passes the production settings (the allowed
hosts, the workers). The image migrates the database before it serves.

Before installing it, put your domain in it: `NEST_ALLOWED_HOSTS=keeper.example.org` becomes your keeper's address.

```sh
scp applications/keeper/deploy/nest-keeper.service server:/tmp/                                  # from your machine
```
```sh
sudo install -m 0644 /tmp/nest-keeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nest-keeper
curl -s http://127.0.0.1:8800/healthz                # {"status":"ok"}
```

`enable` starts it at every boot of the server, after Docker. If it does not come up:
`sudo journalctl -u nest-keeper -n 50`, or run the container by hand once to see Docker's own
message:

```sh
sudo docker run --rm --user "$(stat -c %u:%g /var/snap/docker/common/nest/keeper)" -e HOME=/data -v /var/snap/docker/common/nest/keeper:/data miraur/nest-keeper:latest
```

## 4. Your account, at once

The first account made on a fresh site becomes its administrator (registration is off after
it). Make yours right after the first start, before the domain points at it:

```sh
echo 'a long password' | sudo docker exec -i nest-keeper nest auth create-user /src/nest/applications/keeper you@example.org --role admin --password-stdin
```

## 5. ISPConfig

**Sites → Website**: domain `keeper.example.org`, PHP **disabled**, SSL and
**Let's Encrypt SSL** on. Under
**Options → nginx Directives**, paste `deploy/nginx.conf`: it proxies to `127.0.0.1:8800`. Its `allow` lines can limit the keeper to your own addresses.
The certificate can be made before the site runs.

## 6. The sites it watches

For your Nest sites on this server, the agent tokens in one go (each site's container makes
its own):

```sh
sudo sh /tmp/nest-agent-tokens gari morlaca transilpedia regionalisme docsite
```

It prints each site's address and token: **Watch a site** → *through its agent*, for each.
For a service without a Nest agent (a RoboHub instance): *as a web address*, no token.

The keeper reaches the sites at their public addresses. On a home server, the router may not
let the server reach its own public domains; check from the keeper's container:

```sh
sudo docker exec nest-keeper python -c "import urllib.request; print(urllib.request.urlopen('https://gari.ro/healthz').status)"
```

If that fails, add to the service's `docker run`, after `-e NEST_KEEPER__KEEPER__APPS= \`, a
line `--add-host gari.ro:host-gateway --add-host morlaca.ro:host-gateway … \` (each domain
it watches): the container then reaches nginx on the host directly, with the sites' own
certificates. `daemon-reload`, restart.

Its **Server** buttons (restart and upgrade from the keeper) need the host helper and
`nest-site`, which these services do not use: leave "Name on the server" empty.

## 7. Updates

A new image is built and pushed from a development machine, from Nest's repository, out of
committed code: `deploy/site/nest-images build keeper`, then `push keeper`. On the server:

```sh
sudo docker exec nest-keeper nest backup /src/nest/applications/keeper      # a backup first, in /var/snap/docker/common/nest/keeper/backups/
sudo systemctl restart nest-keeper                        # pulls the new image, migrates, serves
```

To go back to an older version, name its tag in the service
(`Environment=IMAGE=miraur/nest-keeper:0.2.0`), then `sudo systemctl daemon-reload &&
sudo systemctl restart nest-keeper`. If the newer one had migrated the database, restore the
backup made before it, with the service stopped:

```sh
sudo systemctl stop nest-keeper
sudo docker run --rm --user "$(stat -c %u:%g /var/snap/docker/common/nest/keeper)" -v /var/snap/docker/common/nest/keeper:/data miraur/nest-keeper:0.2.0 \
    nest restore /src/nest/applications/keeper /data/backups/<archive> --force
sudo systemctl start nest-keeper
```

## 8. Backups

One a night, 14 kept, by root's crontab (`sudo crontab -e`):

```text
30 3 * * * /snap/bin/docker exec nest-keeper nest backup /src/nest/applications/keeper --keep 14 >/dev/null
```

Each is one archive in `/var/snap/docker/common/nest/keeper/backups/`: the databases (copied consistently while the site
runs), the files, the settings; not the `.env`. **Copy them off the server** too.

## Every day

| | |
|---|---|
| its log | `sudo journalctl -u nest-keeper -f` |
| restart | `sudo systemctl restart nest-keeper` |
| what production asks of it | `sudo docker exec nest-keeper nest check /src/nest/applications/keeper` |
| its migrations | `sudo docker exec nest-keeper nest db status /src/nest/applications/keeper` |
| any nest command | `sudo docker exec -it nest-keeper nest <command> /src/nest/applications/keeper …` |

With Docker from the distribution's packages instead of the snap, the service uses
`/usr/bin/docker` and `docker.service`, and the data folder may be anywhere (`/srv/nest/keeper`).
