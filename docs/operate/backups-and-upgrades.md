---
title: "Backups and upgrades"
description: "nest backup and nest restore, the nightly backup timer, nest-site upgrade with its automatic rollback, and checking migrations."
---

# Backups and upgrades

A Nest site keeps everything it owns in its workspace: its SQLite databases, its stored
files and its settings. A backup is that workspace in one archive. An upgrade with
`nest-site` makes a backup first, so a failed upgrade can put back both the code and the
data as they were.

## `nest backup`

```sh
nest backup APP                      # into the workspace's backups/
nest backup APP --to /mnt/backups    # into another folder
nest backup APP --keep 14            # and keep only the newest 14 there
```

It prints the archive's path and size. The archive is
`<app>-<YYYYMMDD-HHMMSS>.tar.gz` (the time in UTC), first written as a `.partial` file and
renamed only when complete. An interrupted backup therefore never looks like a good one.

### What an archive holds

| Included | How |
|---|---|
| Every SQLite database in the workspace | the bound database, the search index, any other SQLite file. Each is copied with **SQLite's online backup**, a consistent copy taken while the site keeps running |
| Stored files | `media/` (uploads) and the rest of the workspace |
| Settings | `data/settings.conf`, `data/modules.yml` (enabled modules, the theme chosen) |
| Storage outside the workspace | a local storage root that lives elsewhere, under `_storage/` |
| `backup.json` | the format, the application's name, when it was made, the databases, and what was left out |

| Left out | Why |
|---|---|
| `.env` | its secrets belong to the server, not to every copy of a backup |
| `media/_sized` | pictures resized to other widths; they are made again when asked for |
| `backups/` | the earlier archives |
| `-wal`, `-shm`, `-journal` files | already contained in the database's consistent copy |
| a database on a server (PostgreSQL, MariaDB) | back it up with its own tools (`pg_dump`, `mariadb-dump`); `backup.json` names it under `not_included` |

> [!WARNING]
> The `.env` is not in the archive. Keep the secret key and the other secrets somewhere
> safe on their own (on a `nest-site` server they are in `/etc/nest/<site>.env`), or be
> ready to write them again when you restore on a new machine.

## `nest restore`

```sh
nest restore APP ARCHIVE             # into an empty workspace
nest restore APP ARCHIVE --force     # over a workspace that already holds data
```

Stop the application first. `nest restore` checks that the archive is a Nest backup (it has
a `backup.json`) of **this** application, and refuses an archive of another one. Without
`--force`, it also refuses a workspace whose `data/` folder holds anything. Before
extracting, it removes any stale `-wal` and `-shm` files, so an old write-ahead log is never
replayed over the restored copy. Then it prints what the archive did not include.

The same pair moves a site: back it up where it was imported, copy the archive, and restore
it on the server. Each site's `deploy/DEPLOY.md` does exactly this for its first deployment.

## On a server: `nest-site`

On a server set up as in [the ISPConfig guide](../deploy-ispconfig.md), the `nest-site` tool
wraps these commands and runs them inside the site's image, against `/srv/nest/<site>`
mounted at `/data`.

| Command | What it does |
|---|---|
| `sudo nest-site backup S` | a backup now, into `/srv/nest/S/backups/`, keeping `KEEP` (14 by default) |
| `sudo nest-site restore S ARCHIVE` | stops the site, restores with `--force`, starts it, waits for `/healthz`. An archive outside the data folder is copied into `backups/` first |
| `sudo nest-site upgrade S [--no-pull]` | pull, build, back up, restart, wait until healthy; roll back otherwise |
| `sudo nest-site rollback S [ARCHIVE]` | the image before, and the backup made before the upgrade |
| `sudo nest-site nest S ARGS…` | any nest command in the site: in the running container, else in a one-off container |

If the site is running, the backup runs inside it (`docker exec`). Otherwise it runs in a
one-off container of the current image.

### The nightly timer

```sh
sudo systemctl enable --now nest-site-backup@S.timer
systemctl list-timers 'nest-site-backup@*'
```

`nest-site-backup@.timer` runs `nest-site backup S` every night at 03:30, with up to 30
minutes of random delay. `Persistent=true` means a night missed while the server was off is
made up at the next boot. Set `KEEP` in `/etc/nest/S.conf` to change how many archives stay.

## Upgrading: `nest-site upgrade`

```sh
sudo nest-site upgrade S
```

1. **Pull.** `git pull --ff-only` in `/opt/nest/src/nest` and in the site's checkout.
   What gets deployed is what was pushed. `--no-pull` skips this step and builds what is
   there.
2. **Build.** A new image is tagged with both repositories' short commit hashes. The
   previous `:current` becomes `:previous`, and the new one becomes `:current`.
3. **Back up.** If the site is running, a backup is made and its path is remembered in
   `/var/lib/nest-site/S.before-upgrade` (outside the data folder).
4. **Restart.** `systemctl restart nest-site@S`. The image's entrypoint runs
   `nest db upgrade /src/app` (every module's pending migrations), then `nest serve`.
5. **Wait.** It asks `http://127.0.0.1:<PORT>/healthz` every 3 seconds, for up to
   `HEALTH_WAIT` seconds (180 by default). When the site answers, it prints the image and
   `nest db status`, one line per module.
6. **Roll back if needed.** If the site never answers, it prints the last 40 lines of the
   unit's log, runs `nest-site rollback S` and exits with status 1.

### What a rollback does

```sh
sudo nest-site rollback S              # the backup remembered by the last upgrade
sudo nest-site rollback S ARCHIVE      # or a backup you name
```

It refuses when there is no `:previous` image. Otherwise it stops the site, tags the failed
image `:failed` (kept for inspection), and makes `:previous` the `:current` again. It then
**restores the data** from the backup made before the upgrade, with the old image, so the
new version's migrations are undone along with everything else. Finally it starts the site
and waits for `/healthz`.

> [!NOTE]
> A rollback restores the data as they were at step 3. Anything written between that backup
> and the rollback is lost. On a quiet site that is a few seconds; on a busy one, upgrade
> at a quiet hour.

## Migrations: `nest db status`

```sh
nest db status APP                      # in development
sudo nest-site nest S db status /src/app  # on the server
```

It shows, per module, what is applied and what is pending. A production site refuses to
start while anything is pending (`NEST_MIGRATE=check`), unless it was started through the
image's entrypoint, which upgrades first. See [Running Nest sites](overview.md) for the
three `NEST_MIGRATE` modes and [Databases](../develop/database.md) for writing migrations.

## Copy backups off the server

Backups in `/srv/nest/S/backups/` survive a broken container, but not a lost disk. Copy them
elsewhere: rsync the folder to another machine, or include it in the hosting provider's
backup. The archives contain everything except the secrets, so store them where you would
store the site's data.

```sh
rsync -a server:/srv/nest/S/backups/ /backups/S/
```

## Test a restore

A backup you have never restored is a hope. Now and then:

1. take a recent archive to a development machine (or a spare server);
2. `nest restore APP ARCHIVE` into an empty workspace (point `NEST_APP_WORKSPACE` at a
   scratch folder so your own workspace stays untouched);
3. `nest run APP` and look at a few pages, the admin panel and an uploaded picture;
4. `nest check APP` to confirm the databases' integrity.

On the server itself, `sudo nest-site restore S <archive>` does the real thing and puts
the site back on that archive's data.

## `nest check` and backups

`nest check APP` warns when there is no backup yet, or when the newest archive in the
workspace's `backups/` is more than two days old. If that warning appears on a server with
the timer enabled, look at `journalctl -u nest-site-backup@S`.
