---
title: "Changelog"
description: "What changed in each version of Nest."
---
# Changelog

Nest's version is nest-core's (written once, in `packages/nest-core/pyproject.toml`;
`nest --version` says it). Each module, theme, provider, interface and application keeps
a version of its own, in its `module.yml` and its README; the reference pages show them.
This documentation is for **Nest %NEST_VERSION%**.

## 0.4.1

- **core 0.4.1**: `script-src` may be extended with the script sources core reviewed
  (`CSP_SCRIPT_SOURCES`, now only `https://www.googletagmanager.com`); any other script
  source is still refused, and styles stay `'self'`.
- **seo 0.2.0**: Google Analytics (GA4). Admin → Settings → SEO → Google Analytics
  measurement ID (`G-…`) loads Google's tag on every public page (never the admin panel),
  after the visitor agrees when `analytics_consent` is on (the default), with IPs
  anonymized. Themes base 0.2.2, paper, rail-signage and morlaca-valley 0.1.2 include
  `seo/analytics.html` in their layouts.

## 0.4.0

Nest core 0.4.0; the packages that need it say `nest: ">=0.4,<1"` (admin, content,
translations, keeper, registry, the Saga subsystems with rules).

- **trains 0.2.0**: data.gov.ro is asked through its CKAN API only: `package_search`
  filtered by the organisation that publishes the timetables (`sync_organization`,
  `sc-informatica-feroviara-sa`, replacing the free-text `sync_query`), page by page until
  the count; each operator's XML resources by their `format`/`mimetype`; every download
  checked against the `size` the API announces; the portal's own error said when it
  refuses.
- **What fits, and placing it without code** (Nest core, admin, content, forum, glossary,
  feed, every theme): application types (`application.type`: site, game, registry,
  keeper); each package's identity card says its `category` (a fixed list) and the types
  it `fits` (tags: `[site, game]`). The admin panel's Registry shows only what fits the
  site, by category. A module's `offers:` (a menu link, shortcodes, blocks) let an
  administrator place it from its page: a link in a menu, a shortcode in a page, a block
  in a theme's region. **Content → Menus**, a menu manager (links to pages, categories,
  modules, addresses; ordered, nested, translated). **Themes → Regions**: themes declare
  `regions:` (home, after_content, footer, sidebar) and `menus:`; blocks offered by
  content (newest articles), forum (latest topics), feed (readings) and glossary (search).
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
- **feed**: the site serves its own copy of robohub-feed's widget (`static/widget.js`),
  never the `widget.js` a publisher sends (taken and dropped), so a feed's token cannot
  put code on the site.
- **content 0.2.0** and **translations 0.2.0**: a translation's body is written in the same
  rich text editor as the original (`rich_editor()`, which content gives any admin form),
  not as HTML. Rich text is never kept as it was sent: a module that offers an html field
  for translation names its cleaner (`translatable: clean:`, required), and the form and
  imported files pass through it; content cleans a body again when it shows it, and before
  taking its text for the page's description.
- **feed 0.2.0** (new): RoboHub feeds received on a public site. **Admin → Feeds** adds
  one: a name (settlement) and a token made with **Generate**; robohub-feed's `http`
  publisher puts the snapshot and `widget.js` to the site's `/feed` with that token, and
  the site learns the feed's id from the first snapshot. Several feeds, each with its own
  token. The module keeps the latest snapshot and the last 48 values of each item and
  serves them same-origin. A page places a feed with `[feed name="settlement"]` or
  `[feed id="…"]` (`kind="number"`/`"chart"`, `item="i1"`), a template with
  `feed_widget("settlement")`; a feed with no snapshot yet shows nothing.

## Since 0.3.0

Packages released after Nest 0.3.0, each with its own version:

- **forum 0.2.0**: private boards. A board may have a scope (`voievodate/settlement:12`):
  never listed, read and written only by those the application lets in (`forum.access`),
  "not found" for everyone else, live replies included; made on demand by another module
  (`forum.board`). Public boards may show the accounts' own names (`public_names: account`).
  Boards nest to any depth (a board in a board, with the way back up), in every forum,
  private ones included: an inner board has the scope of the one it is in.
  Archiving and deleting (**Admin → Forum**): a board archived is read only, for
  everyone, with every board in it, and listed apart; a board deleted takes every board,
  topic and post in it, after a page that counts them. Topics are archived or deleted too.
  A board's admin page renames it and sets its order.
- **Nest core 0.4.0** and **admin 0.2.0**: the admin menu is grouped (a module's
  `admin: group:` identifiers, an application's `admin_menu:`), each group opening to its pages; a
  module's pages get a **Settings** tab; `admin: settings_role:` lets a role other than
  administrators change that module's settings; settings may have `min` and `max`.
  Nest's own modules are grouped in Content, Community and Site.
- **saga 0.2.0**: `answer_access`, `forum_scope`, `parse_scope`: a subsystem's own forums.
  `rules`: a subsystem's play numbers as its settings, applied to the running world every
  few seconds (`nest_saga.rulebook`).
- **saga subsystems 0.2.0**: 59 rules a game master changes in the admin panel (the market's
  stock and the merchant's share, the monastery's table, ages of apprentices, judges and
  priests, famine relief, plots, fees, and more), each with bounds and a description; the
  subsystems are grouped in the menu (World, People, Economy, Power, Faith).
- **saga player, settlement, guild, polity, monastery 0.2.0**: each settlement's assembly,
  each guild branch's hall, each realm's council, each monastery's board, for their
  members; `people.characters`; `GET /api/joc/<world>/forums` lists a character's boards.

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
