# Running nest-framework.org

Nest-framework.org runs on the server as the Nest registry does: one Docker image, run by a systemd
service, behind an ISPConfig website (nginx, Let's Encrypt). What differs is its data:
**they are not in the image, nor in a Docker volume**, but in a folder on the host,
mounted into the container. Restarting, updating or replacing the container leaves them
as they are.

| | |
|---|---|
| image | `miraur/nest-docsite:latest` |
| service | `nest-docsite` (`deploy/nest-docsite.service`) |
| data | `/srv/nest/docsite` on the host, `/data` in the container |
| secrets, settings | `/etc/nest/docsite.env` (`deploy/docsite.env.example`) |
| port | `127.0.0.1:8700` (loopback only: nginx faces the network) |
| domain | `nest-framework.org` |

## 1. The image

`miraur/nest-docsite:latest`, public on Docker Hub (also `:0.1.0`). It is built and pushed from
Nest's repository, out of committed code only:

```sh
deploy/site/nest-images build docsite
deploy/site/nest-images push docsite
```

It holds the code only. It runs `nest db upgrade`, then serves on port 8000, as an
unprivileged user (uid 10001).

## 2. DNS

An `A` (and `AAAA`) record: `nest-framework.org` → the server, and `www.` too.

## 3. The data, outside the image

`/srv/nest/docsite` on the host, mounted at `/data` in the container: the databases
(`data/app.db`, `data/search.db`), the uploaded files (`media/`), the settings made in the
admin panel (`data/settings.conf`), the backups (`backups/`). The container is thrown away
at each stop; this folder stays, through restarts, new images and going back to an older
one. It belongs to uid 10001, the user the image runs as.

```sh
sudo install -d -m 0755 /srv/nest
sudo install -d -m 0750 -o 10001 -g 10001 /srv/nest/docsite
```

It needs nothing else: the pages are in the image, and the search index is made at the start.

## 4. The environment

The two files the server needs are in this repository's `deploy/` folder, on your machine
(or on GitHub). Copy them over, from the repository's folder:

```sh
scp deploy/docsite.env.example deploy/nest-docsite.service server:/tmp/
```

Then on the server, the environment, filled in:

```sh
sudo install -d -m 0750 /etc/nest
sudo install -m 0600 /tmp/docsite.env.example /etc/nest/docsite.env
sudo editor /etc/nest/docsite.env
```

`NEST_SECRET_KEY` signs the sessions and links: `openssl rand -hex 32`.
One `KEY=VALUE` per line, nothing after the value.

## 5. The service

The service, copied over in step 4:

```sh
sudo install -m 0644 /tmp/nest-docsite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nest-docsite
curl -s http://127.0.0.1:8700/healthz        # {"status":"ok"}
```

At each start it pulls the image (the cached one if Docker Hub cannot be reached), then
runs the container with the data folder mounted. The image migrates the database before it
serves.

## 6. ISPConfig

**Sites → Website**: domain `nest-framework.org`, PHP **disabled**, SSL and **Let's Encrypt SSL**
on; auto-subdomain `www.` and, under **Redirect**, the SEO redirect from `www.nest-framework.org`. Under
**Options → nginx Directives**, paste `deploy/nginx.conf` (it proxies to `127.0.0.1:8700`).

## 7. Updates

After a new image is pushed (step 1):

```sh
sudo docker exec nest-docsite nest backup /src/nest/applications/docsite     # a backup first, in /srv/nest/docsite/backups/
sudo systemctl restart nest-docsite                       # pulls the new image, migrates, serves
```

To go back: `Environment=IMAGE=miraur/nest-docsite:0.1.0` (an older tag) in the service, then
`sudo systemctl daemon-reload && sudo systemctl restart nest-docsite`. If the newer one had
migrated the database, restore the backup made before: stop the service, then
`sudo docker run --rm --env-file /etc/nest/docsite.env -v /srv/nest/docsite:/data miraur/nest-docsite:<that tag> nest restore /src/nest/applications/docsite /data/backups/<archive> --force`.

## 8. Backups

One a night, 14 kept, by root's crontab (`sudo crontab -e`):

```text
30 3 * * * docker exec nest-docsite nest backup /src/nest/applications/docsite --keep 14 >/dev/null
```

Each is one archive in `/srv/nest/docsite/backups/`: the databases (copied consistently while
the site runs), the files, the settings; not the `.env`. **Copy them off the server** too.

## Every day

| | |
|---|---|
| its log | `sudo journalctl -u nest-docsite -f` |
| restart | `sudo systemctl restart nest-docsite` |
| what production asks of it | `sudo docker exec nest-docsite nest check /src/nest/applications/docsite` |
| its migrations | `sudo docker exec nest-docsite nest db status /src/nest/applications/docsite` |
| any nest command | `sudo docker exec -it nest-docsite nest <command> /src/nest/applications/docsite …` |
