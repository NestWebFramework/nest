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

- **flights 0.1.0** (new): the airports of Romania and the Republic of Moldova, for
  aeroportul.ro.
  - 21 airports from OurAirports (public domain, refreshed weekly), with their Romanian
    names.
  - A page each:
    - where it is (km and direction from the town's centre), elevation, codes, runways;
    - what editors add (address, telephone, terminals, parking, taxi, trains and
      shuttles, services, a few words);
    - how to get there: city lines with their next departures and coach stations, asked
      from transport-comun.ro and transportul.ro.
  - A live radar of the aircraft over both countries from adsb.lol (ODbL). It is asked
    only while someone watches, within a daily budget counted for every worker, and
    spaced out as the budget runs low.
  - Search words for every page.
- **transit 0.1.2, coaches 0.1.1:** `/api/v1/aproape?lat=&lon=&km=`, the stops (or coach
  stations) near a point, for other sites.
- **transit-lines 0.1.2:** the `air` variant (a runway with its lights, deep blue and
  amber).

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

- **transit 0.1.1:** exports what other modules build on (its tables, `running`,
  `line_key`, `directions`, the planner as `plan_network`, `plan_journeys`, `forget_plans`,
  `walk_seconds`, and `CommandHost`). coaches uses only these, so it passes the publish
  boundary check.
- **seo 0.2.2:** the batch and the editor's suggestion take a module's own words (below).
- **coaches: stations and towns.**
  - Coach stations (autogări): `/autogari` lists those of Romania and Moldova by county,
    on a map, the busiest first. Each station's page shows its towns reached directly,
    lines, operators, the countries it reaches, the day's departures and arrivals, and
    the town's other stations.
  - What editors add per station (Admin → Coach stations): address, opening hours,
    telephone, website, a few words, and its services (ticket office, waiting room,
    toilets, left luggage, Wi-Fi, step-free access...). Kept by the station's address,
    so it stays when the tables are built again.
  - `/orase`: every town with coaches (Romania's by county, Moldova's, abroad by country),
    with how many towns it reaches and how many reach it. A town page shows the next
    departures and arrivals of its big stations, and the coaches coming to it.
  - Search words for the new pages. Counts use the plural forms ("22 de orașe"). Subjects
    are by address (slug) instead of id, so saved SEO words survive a rebuild.
- **seo:** a module answering `seo.text` with `words` (title, description, keywords)
  gives the batch and the editor's suggestion those words as they are. transit and
  coaches do.
- **coaches 0.1.0** (new): coaches between towns and countries, for transportul.ro, over the
  transit module's intercity and county feeds.
  - Towns: Romania's matched to SIRUTA (2026: names, counties, ranks); abroad from the
    stops, with their Romanian names (Viena, Budapesta).
  - Stations, and the city pairs a coach runs between directly, with their runs a week,
    the quickest time, first and last, operators.
  - Pages: the search, towns, station boards by day, a page per city pair with the day's
    runs (foreign stops in their own time), lines, operators, Europe by country; their
    search words.
  - A JSON API by city pair.
  - Built again after a coach feed loads.
  - **Journeys with changes** over up to three days: a county bus into a coach, a coach into
    another, at least 20 minutes to change and half an hour between two stations of a town
    (Chișinău's Rompetrol to Gara Nord). Several journeys a day, each time in its stop's own
    clock, a link to buy each ride at its operator. A search with no direct coach leads to
    them; a pair with few direct runs shows them too.
- **transit-lines 0.1.1**: a `variant` setting. `lines` (a city's transit map) or `road`
  (coaches between towns: a road with its centre line, a warm accent), for transportul.ro.
- **nest-images** and **nest-agent-tokens** know transportul (port 8620).
- **transit**: a stop's departures over a chosen window (a coach station's whole day); the
  planner's index over any feeds and several days (`planner.network`), with extra transfers.

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
- **Themes** base 0.2.3, paper, rail-signage and morlaca-valley 0.1.3, and transit-lines
  include the consent notice.
- **transit 0.1.0** (new): city and regional public transport. Cities, their lines
  (metro, tram, trolleybus, bus), each line's directions with stops and path, stops with
  the lines serving them and their next departures, stop search, near-me and sitemap
  entries, a JSON list of cities.
  - From GTFS files (fetched only when changed) and the Tranzy API (within its daily
    quota, kept in a ledger).
  - A catalogue of 28 Romanian GTFS feeds and the Tranzy agencies, added from the admin
    panel or `nest transit add`.
  - Stop times are stored as one row per trip: Bucharest's 1.45 million rows become
    66,000.
  - **Live**: where the vehicles are now, and live times on stop boards.
    - GTFS-realtime is read without the protobuf library: vehicles, trip updates,
      alerts (Bucharest, Cluj, Iași, Buzău).
    - Tranzy gives vehicles for Constanța (matched to its GTFS lines by name),
      Botoșani and Chișinău.
    - Fetched only while someone watches a city's live map or a stop's board, by one
      worker for the whole site. Tranzy's interval is worked out from the day's quota
      left, the cities watched and how often their data really changes; stale cities
      are asked less.
    - Live map with gliding vehicles and a line filter; boards with live times,
      delays and cancellations, or arrivals estimated from positions.
  - **Home page**: one search for cities and stops everywhere, and a map of Romania
    and Moldova with every city offered and what it has (lines, stops, timetable,
    live).
  - **Fleet**: every vehicle the live data shows is recorded (at most every ten
    minutes each), with a page per vehicle (fleet number, kind, wheelchair access,
    the lines it ran lately, where it is now) and notes an editor writes.
  - **Learned speeds**: real speeds between stops, by part of the day, learned from
    consecutive positions and used by the arrival estimates instead of a city
    average.
  - **Search words for every page**, written from the data in the page's language: a
    city's lines and kinds, a line's ends, stops and timetable, a stop's lines. Titles,
    descriptions, keywords and breadcrumbs go through the seo module; what an editor
    writes there comes first. The seo module's proposals use the same words.
  - **Coaches between towns and countries** (for transportul.ro):
    - Times written in another zone (FlixBus writes UTC) become local time, split where
      summer time begins or ends or the local date moves past midnight.
    - A feed can keep only the trips touching an area, whole: by its stops' own time zones
      (`tz:Europe/Bucharest,Europe/Chisinau`) or a box. FlixBus's European file becomes its
      37 lines touching Romania and Moldova.
    - Stops keep their own zone (a foreign stop shows its local time).
    - A new `intercity` scope in the catalogue (FlixBus Europe), beside `city` and `county`;
      the cities' pages list only city networks.
  - **Journeys** with changes for the cities with a timetable: RAPTOR on the city's
    day, kept in memory (Bucharest: built in ~0.5 s, then 20–40 ms a journey), walks
    between nearby stops and from "My location", the fastest journey and those with
    fewer changes. A JSON API for journeys, and the API documented in the README.
  - **Admin**: the live state of each city (vehicles, interval, how often the data
    really changes, viewers, stale or failing) and the fleet's notes.
- **transit-lines 0.1.0** (new theme): a transit map's look for a city transport site: a
  white header with a stop's mark, the lines' colours as thin stripes, rounded menu
  pills, clear boards, a dark footer. Made for transport-comun.ro.
- **nest-images** builds and pushes transport-comun too
  (`miraur/nest-sites:transport-comun-…`).
- **maps 0.2.2**: a map tells the page it is ready (`nest-map:ready`, with the map and
  Leaflet), so another module can draw on it.
- **saga survival 0.1.0** (new), **saga player 0.3.0**, **saga npc 0.3.0**: what anyone
  may do to live off the land, with no trade nor guild. Around each settlement (its
  forest, meadow, river, mountain, from the map and the content) a character gathers
  sticks and wood, berries, mushrooms, hazelnuts, herbs, worms, fish, game in snares,
  wild honey, clay, reeds, stones and water, and makes a snare or a rough rod at home:
  a timed act (`do: gather, item: <activity>, hours`), checked first (place, season,
  hour, tools, stamina) and paid for in stamina, hunger and thirst, with risks and
  survival experience. What the land holds is a pool per settlement and resource,
  shared by all who gather there and growing back daily by season. Every home burns
  firewood each day (more in winter); a cold home hurts health in winter. NPCs gather
  too: a home short of firewood sends its people to the forest, those with no trade
  gather what the season gives (npc rules may test a planner `fact` and the `season`;
  actions may `gather`; other subsystems add facts with `npc.facts`).

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
