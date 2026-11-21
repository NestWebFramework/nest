# Running nest-framework.org

Nest-framework.org runs on the server as the Nest registry does: one Docker image from Docker Hub, run by
a systemd service, behind an ISPConfig website (nginx, Let's Encrypt). What differs from the
registry is where its data are: **a plain folder on the server**, mounted into the container.
Restarting, updating or replacing the container leaves the folder as it is, and so it
survives a reboot of the server too.

| | |
|---|---|
| image | `miraur/nest-docsite:latest` (public) |
| service | `nest-docsite`: `applications/docsite/deploy/nest-docsite.service` |
| data | `/var/snap/docker/common/nest/docsite`, owned by the website's user (the container runs as that user) |
| port | `127.0.0.1:8700` (loopback only: nginx faces the network) |
| domain | `nest-framework.org` (and `www.`, redirected) |

The data folder holds everything that changes: the database (`data/app.db`, `data/search.db`),
the uploaded files (`media/`), the settings made in the admin panel (`data/settings.conf`),
the backups (`backups/`), and a `.env` with its secrets (`NEST_SECRET_KEY`, the agent's
token). It is under `/var/snap/docker/common/` because Docker installed from the snap may
mount folders only there (and in `/home`).

## 1. The data folder, empty

The pages are in the image and the search index is made at the start: nothing to bring.
Make the folder and give it to the website's user (ISPConfig's `webN` and `clientN` of
`nest-framework.org`: `stat -c %U:%G /var/www/nest-framework.org/web`):

```sh
sudo mkdir -p /var/snap/docker/common/nest/docsite
sudo chown webN:clientN /var/snap/docker/common/nest/docsite
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
cd /var/snap/docker/common/nest && sudo sh /tmp/nest-secret-key docsite
```

## 3. The service

`applications/docsite/deploy/nest-docsite.service` (this repository) goes to `/etc/systemd/system/`. It pulls the image at each start
(the cached one if Docker Hub cannot be reached), runs the container as the data folder's
owner with the folder mounted at `/data`, and passes the production settings (the allowed
hosts, the workers). The image migrates the database before it serves.

```sh
scp applications/docsite/deploy/nest-docsite.service server:/tmp/                                  # from your machine
```
```sh
sudo install -m 0644 /tmp/nest-docsite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nest-docsite
curl -s http://127.0.0.1:8700/healthz                # {"status":"ok"}
```

`enable` starts it at every boot of the server, after Docker. If it does not come up:
`sudo journalctl -u nest-docsite -n 50`, or run the container by hand once to see Docker's own
message:

```sh
sudo docker run --rm --user "$(stat -c %u:%g /var/snap/docker/common/nest/docsite)" -e HOME=/data -v /var/snap/docker/common/nest/docsite:/data miraur/nest-docsite:latest
```

## 4. Your account, at once

The first account made on a fresh site becomes its administrator (registration is off after
it). Make yours right after the first start, before the domain points at it:

```sh
echo 'a long password' | sudo docker exec -i nest-docsite nest auth create-user /src/nest/applications/docsite you@example.org --role admin --password-stdin
```

## 5. ISPConfig

**Sites → Website**: domain `nest-framework.org`, auto-subdomain `www.`, PHP **disabled**, SSL and
**Let's Encrypt SSL** on; under **Redirect**, the SEO redirect from `www.nest-framework.org` to `nest-framework.org`. Under
**Options → nginx Directives**, paste `deploy/nginx.conf`: it proxies to `127.0.0.1:8700`.
The certificate can be made before the site runs.

## 6. The keeper (optional)

The site has Nest's agent at `/_agent`; a keeper watches it there (up or down, versions,
migrations, backups, recent errors). The agent answers nobody until it has a token:

```sh
sudo sh /tmp/nest-agent-tokens docsite
```

The script has the site's container make a token, puts its SHA-256 in the data folder's
`.env`, restarts the site, checks the agent answers, and prints the token. In the keeper:
**Watch a site** → *through its agent*, `https://nest-framework.org` and that token.

## 7. Updates

A new image is built and pushed from a development machine, from Nest's repository, out of
committed code: `deploy/site/nest-images build docsite`, then `push docsite`. On the server:

```sh
sudo docker exec nest-docsite nest backup /src/nest/applications/docsite      # a backup first, in /var/snap/docker/common/nest/docsite/backups/
sudo systemctl restart nest-docsite                        # pulls the new image, migrates, serves
```

To go back to an older version, name its tag in the service
(`Environment=IMAGE=miraur/nest-docsite:0.1.0`), then `sudo systemctl daemon-reload &&
sudo systemctl restart nest-docsite`. If the newer one had migrated the database, restore the
backup made before it, with the service stopped:

```sh
sudo systemctl stop nest-docsite
sudo docker run --rm --user "$(stat -c %u:%g /var/snap/docker/common/nest/docsite)" -v /var/snap/docker/common/nest/docsite:/data miraur/nest-docsite:0.1.0 \
    nest restore /src/nest/applications/docsite /data/backups/<archive> --force
sudo systemctl start nest-docsite
```

## 8. Backups

One a night, 14 kept, by root's crontab (`sudo crontab -e`):

```text
30 3 * * * /snap/bin/docker exec nest-docsite nest backup /src/nest/applications/docsite --keep 14 >/dev/null
```

Each is one archive in `/var/snap/docker/common/nest/docsite/backups/`: the databases (copied consistently while the site
runs), the files, the settings; not the `.env`. **Copy them off the server** too.

## Every day

| | |
|---|---|
| its log | `sudo journalctl -u nest-docsite -f` |
| restart | `sudo systemctl restart nest-docsite` |
| what production asks of it | `sudo docker exec nest-docsite nest check /src/nest/applications/docsite` |
| its migrations | `sudo docker exec nest-docsite nest db status /src/nest/applications/docsite` |
| any nest command | `sudo docker exec -it nest-docsite nest <command> /src/nest/applications/docsite …` |

With Docker from the distribution's packages instead of the snap, the service uses
`/usr/bin/docker` and `docker.service`, and the data folder may be anywhere (`/srv/nest/docsite`).
