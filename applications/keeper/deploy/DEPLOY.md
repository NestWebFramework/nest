# Deploying the keeper

The keeper watches your deployed sites: Nest sites through their agents, any other service
(a RoboHub instance, say) with a web check. It can restart, back up, upgrade and roll back
the Nest sites on its own server through the host helper. It is one person's tool: you run
your own, on a domain of yours. This kit uses `keeper.example.org`: put your own domain in
`keeper.env` and `nginx.conf`.

It runs like every Nest site on the server: a container (`nest-site@keeper`), its data on
the host (`/srv/nest/keeper`), behind nginx. See `docs/deploy-ispconfig.md` for the server
itself (Docker, `nest-site`, the systemd units).

## 1. The keeper

```sh
sudo install -m 0640 /opt/nest/src/nest/applications/keeper/deploy/site.conf.example /etc/nest/keeper.conf
sudo nest-site init keeper              # /srv/nest/keeper, and /etc/nest/keeper.env with a fresh secret
sudo editor /etc/nest/keeper.env         # the rest, from deploy/keeper.env.example
sudo nest-site build keeper
sudo systemctl enable --now nest-site@keeper nest-site-backup@keeper.timer
```

## 2. Your account, before the domain is on

The first account made on a fresh keeper becomes its administrator. Make yours from the
server, before nginx sends anyone to it:

```sh
sudo nest-site nest keeper auth create-user /src/nest/applications/keeper you@example.org --role admin --password-stdin
```

Registration stays off (`auth.allow_registration` is false): nobody else can make an
account. Others who want a keeper run their own (docs: "Run your own keeper").

## 3. The domain

ISPConfig → Sites → Website `keeper.example.org`: PHP disabled, Let's Encrypt on; under
**Options → nginx Directives**, `deploy/nginx.conf`. It proxies to `127.0.0.1:8800`. Its
`allow` lines can limit the keeper to your own addresses.

Then sign in at `https://keeper.example.org/cont/login`.

## 4. The sites it watches

For each Nest site, on the server (or any machine with Nest):

```sh
nest agent token gari                  # or --control, to also run its actions
```

Put the `NEST_GARI__AGENT__…_TOKEN=sha256:…` line in `/etc/nest/gari.env`, run
`sudo nest-site restart gari`, then **Watch a site** in the keeper with
`https://gari.ro` and the `na_…` token. The keeper reaches each site at its public address.

For a service without an agent (a RoboHub instance), choose **as a web address**: the keeper
asks the address and counts an answer below 400 as up. A service that answers the agent's
status format (docs: "The agent's status format") gets the full card.

## 5. Restarts and upgrades (optional)

Install the host helper (`docs/deploy-ispconfig.md`, "Restarts and upgrades from the
keeper") with `BIND=172.17.0.1` in `/etc/nest/host.conf`. The keeper's container reaches the
host there. If ufw guards the host, let the containers in:

```sh
sudo ufw allow in on docker0 to 172.17.0.1 port 8090 proto tcp
```

Then, in `/etc/nest/keeper.env`:

```text
NEST_KEEPER__KEEPER__HOST_URL=http://172.17.0.1:8090
NEST_KEEPER__KEEPER__HOST_TOKEN=nh_…
```

and `sudo nest-site restart keeper`. On each Nest site's **Change** page, give its name on
the server (`gari`): its page gets the Server section.

## Upgrades

```sh
sudo nest-site upgrade keeper
```

It pulls Nest's sources, builds, backs up, migrates and restarts, and rolls back by itself
if the new keeper is not healthy. The keeper can also be upgraded from its own page
through the host helper (give it the name `keeper` on the server), but the page goes away
while it restarts, so the job's output is lost from view. It is still written to
`journalctl -u nest-host`.
