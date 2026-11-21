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

- **feed** (new): a RoboHub feed received on a public site. robohub-feed's `http`
  publisher puts the snapshot and `widget.js` with a token per feed; the module keeps the
  latest snapshot and the last 48 values of each item, serves them same-origin, and
  places the widget with `feed_widget("settlement")`.

## Unreleased

- **feed** (new): a RoboHub feed received on a public site. robohub-feed's `http`
  publisher puts the snapshot and `widget.js` with a token per feed; the module keeps the
  latest snapshot and the last 48 values of each item, serves them same-origin, and
  places the widget with `feed_widget("settlement")`.

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

- **trains**: the timetable from data.gov.ro's CFR XML files, followed by itself (the new
  year in December); journeys with changes (Connection Scan Algorithm), through a station,
  direct only, by day; running days; trains' cars drawn, replacement buses; split-flap,
  LED and station boards other sites embed, and their webmasters' page; the trains
  running now on a map; stations' places checked against the tracks; an old site's
  addresses; an admin panel for the timetable.
- **geo**: where the reader is and what is near: a near-me page every module with places
  contributes to (`geo.near`), distances, a locate button.
- **hangman**: a word game on any module's words (`words.random`).
- **glossary**: visitors' proposals approved by editors; comments on terms; definitions
  explained in other languages (the words not translated); a webmasters' search box;
  dictionaries managed in the admin panel; Glossword database imports.
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
- **scheduler** (new): jobs at set times or intervals, declared in the packages' manifests
  (`schedule:`, `every: 6h` or `cron: "30 3 * * *"`), changed by the application, run once
  across workers and containers (a lease in the database), remembered across restarts, in
  their own threads; Admin → Scheduler, `nest scheduler jobs|run`. The timetable's sync
  (`trains.sync`, every 6 hours) and the keeper's checks (`keeper.watch`, every 5
  minutes; `keeper.prune`, nightly) are its first jobs.
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

- **rail-signage**: Romanian station signage.
- The **morlaca** themes take a top **menu** setting; **morlaca-chronicle**'s footer compact.

**Core**

- `nest.security.allow(response, "embed" | "geolocation")`: one page framed by other sites,
  or allowed to ask where the reader is; every other keeps the strict policy.
- `ModuleHost.translator()`, `ModuleHost.app_root`.

## 0.2

Plug-and-play modules (core and optional, enabled per application), the registry and
`nest packages`, `nest serve` (gunicorn master, uvicorn workers) with shared state and live
updates across workers, the Saga game engine as a process of its own, themes chosen in the
admin panel (paper, slate), languages with an address each, the content, gallery, maps,
seo, redirects, notifications and translations modules, one image for any application.

## 0.1

The host: manifests, the catalog and the plan, interfaces and providers, modules that own
no port, the admin panel, accounts, the first sites.
