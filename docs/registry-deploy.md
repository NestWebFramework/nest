# Running registry.nest-framework.org

The registry is one Docker image (`applications/registry/deploy/Dockerfile`), run as a
systemd service on the server, behind its nginx (ISPConfig's vhost), as Rho's registry is.
It keeps its database and files in a volume, or in PostgreSQL and S3/MinIO on a dedicated
server: only its environment changes.

## 1. The image

It is on Docker Hub as `miraur/nest-registry`; GitHub builds and pushes it on every version
tag (`.github/workflows/registry-image.yml`, with the repository secrets
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`). By hand, from Nest's repository:

```
docker build -f applications/registry/deploy/Dockerfile -t miraur/nest-registry:latest .
docker push miraur/nest-registry:latest
```

The image runs `nest db upgrade`, then `nest serve` (gunicorn's master and its workers) on
port 8000, as an unprivileged user; `/data` is its workspace. If the repository is private
on Docker Hub, log the server in once: `docker login` (an access token with read access).

## 2. DNS

An `A` (and `AAAA`) record: `registry.nest-framework.org` → the server.

## 3. The environment

```
sudo install -d -m 0750 /etc/nest
sudo install -m 0600 applications/registry/deploy/registry.env.example /etc/nest/registry.env
sudo editor /etc/nest/registry.env       # NEST_SECRET_KEY: openssl rand -hex 32
```

By default the database is SQLite and the files are on the volume; for PostgreSQL and
MinIO, uncomment their lines (`NEST_BIND__NEST_DB=db-postgres` and its URL,
`NEST_BIND__NEST_STORAGE=storage-s3` and its endpoint, bucket and keys).

## 4. The service

```
sudo install -m 0644 applications/registry/deploy/registry-docker.service /etc/systemd/system/nest-registry.service
sudo systemctl daemon-reload
sudo systemctl enable --now nest-registry
curl -s http://127.0.0.1:8600/healthz          # {"status":"ok"...}
```

The container listens on `127.0.0.1:8600` only: nginx is what faces the network.
(`deploy/compose.yml` does the same with docker compose, and can run PostgreSQL and MinIO
beside it with the profile `services`.)

## 5. ISPConfig (nginx)

In ISPConfig: **Sites → Website → Add new website**

- Domain: `registry.nest-framework.org`; PHP: disabled; SSL and **Let's Encrypt SSL**: on.
- **Options → nginx Directives**:

```
client_max_body_size 60m;

location / {
    proxy_pass http://127.0.0.1:8600;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    proxy_request_buffering off;
}
```

ISPConfig writes the vhost and renews the certificate. Without ISPConfig,
`deploy/nginx.conf` is the same as a plain nginx server block.

## 6. The first administrator, the publishers

```
echo 'a long password' | docker exec -i nest-registry nest auth create-user /src/nest/applications/registry you@example.org --role admin --password-stdin
```

Sign in at https://registry.nest-framework.org/cont/login. Nobody signs up on their own:
administrators make the accounts (as above, or in the admin panel's Accounts) and give the
`publisher` role to those that may publish, as the registry's `publishers: approved` setting
says. Sign-up can be opened from the environment: `NEST_REGISTRY_APP__AUTH__ALLOW_REGISTRATION=true`.

## 7. Publishing Nest's own packages

On your machine (or in CI):

```
nest login --registry https://registry.nest-framework.org     # a token from its Tokens page
nest keygen --register                                         # sign what you publish
nest publish --all                                             # every package, nest-core too
```

For GitHub Actions, put an administrator's token in the repository secret
`NEST_REGISTRY_TOKEN` (and, to sign there, the private key's PEM in `NEST_SIGNING_KEY`):
every `v*` tag then tests and publishes what changed (`.github/workflows/publish.yml`).

## Upgrades, backups

- **Upgrade**: a new image is pulled at each start: `sudo systemctl restart nest-registry`
  (the migrations run before it serves).
- **Backup** (SQLite and the volume): `docker exec nest-registry nest backup /src/nest/applications/registry`
  writes an archive into the volume's `backups/`; copy it off the server. With PostgreSQL
  and MinIO, back those up with their own tools (`pg_dump`, `mc mirror`).
- **Logs**: `journalctl -u nest-registry -f`, or `docker logs -f nest-registry`.
