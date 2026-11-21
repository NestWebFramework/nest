# Running the keeper

The keeper runs on the server as the Nest registry does: one Docker image, run by a systemd
service, behind an ISPConfig website (nginx, Let's Encrypt). What differs is its data:
**they are not in the image, nor in a Docker volume**, but in a folder on the host,
mounted into the container. Restarting, updating or replacing the container leaves them
as they are.

| | |
|---|---|
| image | `miraur/nest-keeper:latest` |
| service | `nest-keeper` (`deploy/nest-keeper.service`) |
| data | `/srv/nest/keeper` on the host, `/data` in the container |
| secrets, settings | `/etc/nest/keeper.env` (`deploy/keeper.env.example`) |
| port | `127.0.0.1:8800` (loopback only: nginx faces the network) |
| domain | `keeper.example.org` |

## 1. The image

`miraur/nest-keeper:latest`, public on Docker Hub (also `:0.2.0`). It is built and pushed from
Nest's repository, out of committed code only:

```sh
deploy/site/nest-images build keeper
deploy/site/nest-images push keeper
```

It holds the code only. It runs `nest db upgrade`, then serves on port 8000, as an
unprivileged user (uid 10001).

## 2. DNS

An `A` (and `AAAA`) record: `keeper.example.org` → the server.

## 3. The data, outside the image

`/srv/nest/keeper` on the host, mounted at `/data` in the container: the databases
(`data/app.db`, `data/search.db`), the uploaded files (`media/`), the settings made in the
admin panel (`data/settings.conf`), the backups (`backups/`). The container is thrown away
at each stop; this folder stays, through restarts, new images and going back to an older
one. It belongs to uid 10001, the user the image runs as.

```sh
sudo install -d -m 0755 /srv/nest
sudo install -d -m 0750 -o 10001 -g 10001 /srv/nest/keeper
```

Once the service runs, and **before** the domain points at it, make your account (the first
account of a fresh keeper becomes its administrator; registration is off after it):

```sh
echo 'a long password' | sudo docker exec -i nest-keeper nest auth create-user /src/nest/applications/keeper you@example.org --role admin --password-stdin
```

## 4. The environment

The two files the server needs are in this repository's `deploy/` folder, on your machine
(or on GitHub). Copy them over, from the repository's folder:

```sh
scp deploy/keeper.env.example deploy/nest-keeper.service server:/tmp/
```

Then on the server, the environment, filled in:

```sh
sudo install -d -m 0750 /etc/nest
sudo install -m 0600 /tmp/keeper.env.example /etc/nest/keeper.env
sudo editor /etc/nest/keeper.env
```

`NEST_SECRET_KEY` signs the sessions and links: `openssl rand -hex 32`.
One `KEY=VALUE` per line, nothing after the value.

## 5. The service

The service, copied over in step 4:

```sh
sudo install -m 0644 /tmp/nest-keeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nest-keeper
curl -s http://127.0.0.1:8800/healthz        # {"status":"ok"}
```

At each start it pulls the image (the cached one if Docker Hub cannot be reached), then
runs the container with the data folder mounted. The image migrates the database before it
serves.

## 6. ISPConfig

**Sites → Website**: domain `keeper.example.org`, PHP **disabled**, SSL and **Let's Encrypt SSL**
on. Under
**Options → nginx Directives**, paste `deploy/nginx.conf` (it proxies to `127.0.0.1:8800`).

## 7. Updates

After a new image is pushed (step 1):

```sh
sudo docker exec nest-keeper nest backup /src/nest/applications/keeper     # a backup first, in /srv/nest/keeper/backups/
sudo systemctl restart nest-keeper                       # pulls the new image, migrates, serves
```

To go back: `Environment=IMAGE=miraur/nest-keeper:0.2.0` (an older tag) in the service, then
`sudo systemctl daemon-reload && sudo systemctl restart nest-keeper`. If the newer one had
migrated the database, restore the backup made before: stop the service, then
`sudo docker run --rm --env-file /etc/nest/keeper.env -v /srv/nest/keeper:/data miraur/nest-keeper:<that tag> nest restore /src/nest/applications/keeper /data/backups/<archive> --force`.

## 8. Backups

One a night, 14 kept, by root's crontab (`sudo crontab -e`):

```text
30 3 * * * docker exec nest-keeper nest backup /src/nest/applications/keeper --keep 14 >/dev/null
```

Each is one archive in `/srv/nest/keeper/backups/`: the databases (copied consistently while
the site runs), the files, the settings; not the `.env`. **Copy them off the server** too.

## Watching the sites, restarting them

In the keeper, **Watch a site** for each one: its address and its agent's token (each site's
DEPLOY.md, "The keeper"). For services without a Nest agent (a RoboHub instance), choose
**as a web address**.

To restart, back up and upgrade the sites from the keeper, install the host helper
(Nest's `docs/deploy-ispconfig.md`, "Restarts and upgrades from the keeper") with
`BIND=172.17.0.1`, and set `NEST_KEEPER__KEEPER__HOST_URL` and `..._HOST_TOKEN` in
`/etc/nest/keeper.env`.

## Every day

| | |
|---|---|
| its log | `sudo journalctl -u nest-keeper -f` |
| restart | `sudo systemctl restart nest-keeper` |
| what production asks of it | `sudo docker exec nest-keeper nest check /src/nest/applications/keeper` |
| its migrations | `sudo docker exec nest-keeper nest db status /src/nest/applications/keeper` |
| any nest command | `sudo docker exec -it nest-keeper nest <command> /src/nest/applications/keeper …` |
