---
title: "Changelog"
description: "What changed in each version of Nest."
---
# Changelog

Nest's version is nest-core's (written once, in `packages/nest-core/pyproject.toml`;
`nest --version` says it). Each module, theme, provider, interface and application keeps
a version of its own, in its `module.yml` and its README; the reference pages show them.
This documentation is for **Nest %NEST_VERSION%**.

## Unreleased

- **The keeper's copies kept apart, a cut-off restore unlocks** (keeper 0.3.1, the keeper
  application 0.3.1): a site's backup folder is never one already on disk (a site removed
  leaves its copies; a new one of the same name gets its own folder); copies are ordered and
  pruned by the time in their names, whatever the application's name. `nest-host`: a download
  from the keeper cut off, refused or not kept (a full disk) fails the restore cleanly, leaves
  no `.partial`, and never leaves the site locked.

- **The keeper keeps the sites' backups, and puts them back** (keeper 0.3.0, agent 0.2.0,
  the keeper application 0.3.0): with `backup_dir`, the keeper copies every site's backups
  each night (`keeper.fetch`) through its agent (`GET /_agent/v1/backups`, and each archive
  to the control token), checks each against its SHA-256 and keeps the newest
  `backup_keep` per site; a site behind another server's Cloudflare tunnel is copied the
  same way. **Servers** in the keeper: each server's `nest-host`, its token and its
  Cloudflare Access service token (kept encrypted), a site acted on by its server's helper
  (`host_url` stays the helper of sites with none; migration `keeper_0005`). **Restore…**
  on a site's page: an archive of its server, or the keeper's copy, which the helper
  downloads through a one-time link (`KEEPER_URL` in `host.conf`) and checks before
  anything is replaced; `restore` only when `ALLOW` names it. `nest-site restore` backs the
  site up first. The agent keeps 14 backups when asked for one (as `nest-site`'s `KEEP`;
  it was 7, and pruned the nightly ones).

## 0.4.7

- **Nest is MIT-licensed, said once at its root**: a `LICENSE` file, the README and the
  workspace's `pyproject.toml` (every package and module already said MIT).

## 0.4.6

- **nest-core: the machine's own health checks** (Docker's, every 30 seconds, from
  127.0.0.1) are left out of the access log, in production (gunicorn) and with `nest run`;
  visitors' lines, and health checks from outside, stay.
- **push 0.1.0: notifications on a visitor's device (Web Push), for any module.** Any
  module schedules what to say and when (`push.schedule`); every 30 seconds what is due is
  sent, after the module looks again (its `recheck` lookup: move it, change it, drop it).
  VAPID and RFC 8291 encryption with the `cryptography` package only (checked against the
  RFC's own example). Kept: the browser's push address, sealed under the site's key, and
  what waits for it; deleted once sent, or when the push service says the address is gone.
  Only the browsers' own push services are posted to.

## 0.4.5

- **nest-core 0.4.5:** a signed-in visitor's pages are sent `Cache-Control: private,
  no-cache` (no cache keeps them, nor the service worker); the web app's addresses
  (/sw.js, /manifest.webmanifest, /offline, /.well-known/) are one each, whatever the
  visitor's language.

## 0.4.4

- **base 0.2.4: checkboxes and radio buttons one size everywhere.** The form fields'
  style (full width, padding, a minimum height) is for text fields, lists and text areas
  only. Checkboxes and radios are 1.1rem in the site's accent colour, beside their words,
  on the sites and in the admin panel. Before, those outside a few wrapper classes came
  out bigger.

- **consent 0.1.1:** the lookup `consent.allowed`, so other modules can check a purpose
  without importing consent.

## 0.4.3

- **Module versions apply everywhere at once (nest-core 0.4.3, admin 0.2.2).** Choosing a
  version in the panel could leave the site running both: one worker on the new version,
  the others on the old. Refreshes then flipped between them.
  - A worker now signals its parent, the nest serve master, to reload every worker. A pid
    file may be stale or name a process in another namespace.
  - A worker never reloads alone: without its master, the change applies at the next
    restart.
  - A worker forked from the master (renewed after max_requests, or made when the master
    missed a reload) takes the versions chosen since, and drops the old code.
  - The change runs in the background. The page answers at once, shows it under way
    (download, checks, backup, migrations, reload), then reloads and says what was done or
    why not. Before, a change longer than the proxy's timeout (nginx, Cloudflare) showed
    nothing. One change at a time.
- **htmx 0.1.2: no request fails silently.** An answer that says why a form was refused
  (400, 409, 422) is shown. A server error, a proxy timeout or no network is told
  (a toast, or a notice).
- **auth 0.4.2: brute-force protection.**
  - An account is paused after 3 wrong passwords, from any address (`account_attempts`).
    Unknown emails are counted the same, so a pause tells nothing of who has an account.
  - An address is paused after 20 failures, on any accounts (`address_attempts`).
  - Pauses last `lockout_minutes` (15) and answer with `Retry-After`.
  - A wrong password waits about half a second before answering.
  - Guessing the current password on the account page counts against the account.
  - An address may create at most `registrations_per_hour` (5) accounts an hour.
  - Passwords easy to guess are refused: the most common ones, also with digits or signs
    after them; runs of one or two characters; keyboard and alphabet rows; ones built
    from the email.

- **seo 0.2.2:** the batch and the editor's suggestion take a module's own words (below).

## 0.4.2

- **core 0.4.2**: on a site with an address per language (`language_urls: prefix`), a first
  visit's form was refused ("CSRF cookie missing"). The middleware that reads the language
  from the address replaced the request's state, so the page's use of the form token was
  lost and the form's cookie was never set. The state is now updated in place.
- **consent 0.1.0** (new): cookies and consent for a whole site.
  - Every module declares its cookies, as configured now (`consent.cookies`); Nest's own
    are declared for it.
  - One notice, in plain words, asks only for the purposes that need consent: OK, Only the
    essential, or Choose (a switch per purpose).
  - The cookies page lists every cookie by purpose, who sets it and for how long, with a
    switch per service when a purpose has more than one.
  - Every module asks the same choice: in templates, in Python, in page scripts. A new
    cookie that needs consent asks again.
- **seo 0.2.1**: Google Analytics declares its cookies and, with the consent module, loads
  only once the visitor allowed statistics (its own question otherwise, now in plain
  words).
- **nest-images** builds and pushes transport-comun too
  (`miraur/nest-sites:transport-comun-…`).
- **maps 0.2.2**: a map tells the page it is ready (`nest-map:ready`, with the map and
  Leaflet), so another module can draw on it.

## 0.4.1

- **core 0.4.1**: `script-src` may be extended with the script sources core reviewed
  (`CSP_SCRIPT_SOURCES`, now only `https://www.googletagmanager.com`); any other script
  source is still refused, and styles stay `'self'`.

## 0.4.0

Nest core 0.4.0; the packages that need it say `nest: ">=0.4,<1"` (admin, content,
translations, keeper, registry).

- **Packages named by their identifiers, never by their words** (Nest core, every
  package): a package's title, description and admin page's words are in its own catalog
  under `@` keys (`"@title"`, `"@admin.title"`…, kept as `forum@title`), shown with
  `about(name, field, default)`; admin menu groups are identifiers (`admin: group:
  economy`, `admin_menu: [{group: economy, …}]`, labels `group@economy`). Every package
  has its Romanian words.
- **Module versions on a running site** (Nest core 0.4.0, admin 0.2.0): Admin → Modules in four
  tabs (Installed, Updates, Registry, History). Update a module, **Update all**, take one
  to any version in the registry (up or down) or back to the image's, add a module or a
  theme from the registry with the Nest packages it needs. The versions chosen are kept
  in the workspace (`packages/`, `nest.overlay`), so they survive a container's restart;
  a newer image wins over an older choice. Each change is checked (registry, sha256,
  signature when pinned, what it needs), backed up, migrated (down first for an older
  version, up after), proven to start in a new process, undone if it does not, and
  logged. A module's page moves its migrations up or down to any revision.
  `nest modules APP versions | version | migrations | migrate` do the same from a shell.
- **content 0.2.0** and **translations 0.2.0**: a translation's body is written in the same
  rich text editor as the original (`rich_editor()`, which content gives any admin form),
  not as HTML. Rich text is never kept as it was sent: a module that offers an html field
  for translation names its cleaner (`translatable: clean:`, required), and the form and
  imported files pass through it; content cleans a body again when it shows it, and before
  taking its text for the page's description.

## Since 0.3.0

Packages released after Nest 0.3.0, each with its own version:

- **Nest core 0.4.0** and **admin 0.2.0**: the admin menu is grouped (a module's
  `admin: group:` identifiers, an application's `admin_menu:`), each group opening to its pages; a
  module's pages get a **Settings** tab; `admin: settings_role:` lets a role other than
  administrators change that module's settings; settings may have `min` and `max`.
  Nest's own modules are grouped in Content, Community and Site.

## 0.3.0

**Documentation and running sites**

- **nest-framework.org**: the documentation site (`applications/docsite`), served by the
  new **docs** module: Markdown pages in a tree, a menu, search, pictures, and a reference
  page for every package, made from its manifest.
- **Deployment on a server with ISPConfig**: `deploy/site/` (the `nest-site` tool, the
  systemd units `nest-site@` and `nest-site-backup@`): one container per site, its data on
  the host, upgrades that back up, migrate and roll back by themselves.
- Every page's footer says it is built with Nest (`nest_credit`, asked by the theme contract).
- `nest --version`; versions stated in every package's and application's README.

**Modules**

- **docs**: as above.
- **agent** (new): a site's status, events, `nest check` and actions (a backup; a module's
  own, as the timetable's sync), for the keeper, to a token whose SHA-256 is all the site
  keeps (`nest agent token APP [--control]`).
- **keeper** 0.2.0: a dashboard of the deployed sites it watches through their agents:
  up or down and since when, uptime over 24 hours and 7 days, answer time, versions,
  pending migrations, backups, recent events, the production check, and the actions each
  site allows, with who ran which. The agents' tokens are kept encrypted.
- **keeper**: web checks for services that are not Nest sites (any address: up if it
  answers below 400); the agent's status format documented for other programs to answer;
  its own deployment kit (`applications/keeper/deploy/`): run your own keeper.
- **core**: `ModuleHost.host_of(package)` and `ModuleHost.app_name`.
- **nest-host** (`deploy/site/`): the keeper's hands on the server: restart, back up,
  upgrade and roll back the sites `nest-site` runs, from a site's page in the keeper,
  to a token; only those actions, only known sites, every job logged with who asked.
- **db**: `pending_migrations(nest)`, the modules of a running application behind their tables.
- **maps**: a map any module puts on its page (`maps.element`), lines and dots, maps that
  refresh themselves.
- **seo**: proposals for the pages of every module (`seo.text`), batches of thousands of pages.
- **admin**: what waits for someone shown on the panel's tiles (`admin.waiting`).
- **comments**: GentleSource (Glossword) imports.
- **redirects**: another module may ask it about an old address (`redirects.request`).

**Themes**

**Core**

- `nest.security.allow(response, "embed" | "geolocation")`: one page framed by other sites,
  or allowed to ask where the reader is; every other keeps the strict policy.
- `ModuleHost.translator()`, `ModuleHost.app_root`.

## 0.2

Plug-and-play modules (core and optional, enabled per application), the registry and
`nest packages`, `nest serve` (gunicorn master, uvicorn workers) with shared state and live
updates across workers, themes chosen in the
admin panel (paper, slate), languages with an address each, the content, gallery, maps,
seo, redirects, notifications and translations modules, one image for any application.

## 0.1

The host: manifests, the catalog and the plan, interfaces and providers, modules that own
no port, the admin panel, accounts, the first sites.
