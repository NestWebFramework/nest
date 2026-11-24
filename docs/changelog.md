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

- **Saga farm 0.3.0: a player's own fields and garden** (player 0.4.1, property 0.2.2): its
  share of the household's land (or a strip worked "în parte") and a garden; the content's
  works by each crop's calendar (plough, sow, dig, weed, water, reap: `works:`; crops'
  `seed`, `produce`, `place`), done a few hours at a time and counted in pogoane; oxen
  plough faster (`property.owned`); the harvest by how the land's crop fared and the care
  given, less the tithe (settings `garden`, `strip`, `share`, `tithe`, `tend_most`); the
  player's `farm` act; `farm.reaped`.

- **clujul-online.ro brought back** (a Joomla 1.5 city portal of 2012–2013), and what it
  needed, for any site:
  - **content 0.2.5**: `nest content import-joomla` (articles, GMapFP map places as
    entries with coordinates, address, phones, hours and categories, efemerides as dated
    entries; contact persons left out); the RSS feed of a subject (`/feed/?q=Cluj`,
    `&titlu=1` for titles naming it) or of chosen entries (`/feed/?cai=/a/,/b/`, in that
    order), each item with its picture; `latest()` of any taxonomy's term; the
    `content.entries` lookup.
  - **gallery 0.3.3**: `nest gallery import-joomgallery` (categories as galleries with
    their tree, photos from originals with JoomGallery's thumbnails).
  - **maps 0.2.3**: `[map places="1"]`, every place the site's modules know.
  - New **almanac** module: each day's fixed feasts of the orthodox and catholic
    calendars (366 days, from the 2012 calendars; the movable feasts left out), the
    site's on-this-day entries, a page per day (`/astazi/11-24/`), a block, `[astazi]`.
  - New **nearby** module: beside a place, its nearest stops with their next departures,
    and the station, coach station or airport when near (transport-comun.ro, gari.ro,
    transportul.ro, aeroportul.ro); `[aproape lat lng tip]` in a page's text.
  - New **headlines** module: the day's news from the feeds a site sets (RSS, Atom):
    titles and links only, nofollow, its page noindex; featured feeds as cards with
    their pictures kept locally (`[recomandate]`, `features()`).
  - New theme **clujul-gazeta**: a nineteenth-century city gazette (Playfair Display,
    EB Garamond, Cormorant SC served locally), the day's date and saints, news column,
    featured cards, places with their facts and "how to get there".
- **Voievodate playable** (auth 0.4.3; Saga player 0.4.0, guild 0.3.0, quest 0.3.0):
  auth's `after_register` (where a new account lands); absent players looked after by kin
  and neighbours (`away_hours`, `away_floor`); day labour with no trade (`day_wage`);
  apprenticeship with any grown village master (`village_fee`, `village_master_age`);
  start quests given at birth (`start: true`).

- **coaches 0.1.4, flights 0.1.7: stars on coach stations and airports** (the rating module;
  transportul.ro and aeroportul.ro), under their titles.
- **Pictures in articles shown as the gallery shows its photos** (content 0.2.4, gallery
  0.3.2):
  - The editor's new **Emphasize** button on a picture (it toggles, like bold; the class
    `evidentiat`): framed, full width, its description under it, a magnifier; a tap opens
    it large in the gallery's viewer. Emphasized pictures side by side are a
    **mini-gallery**, a row of tiles.
  - The content setting **pictures_open_large**: every picture in an entry opens large in
    the viewer; all of an article's pictures are one series (the viewer's arrows).
  - A picture that links to another page keeps its link; another site's pictures are left
    alone; without JavaScript each is a link to its large picture. morlaca.ro and
    transilpedia.ro open every picture large.

- **content 0.2.3: imported posts' old links fixed where they are shown** (no re-import):
  a link to the old server (a bare IP, often with a folder: http://79.118.74.35/morlaca/)
  becomes this site's; an old post number (?p=27) goes to that entry's address now; a
  picture linked to its own post, or to an attachment page no longer there, opens the
  picture itself; another site's ?p= pages are left alone. The featured image is not shown
  above the text when the text starts with the same picture (the picture twice, as
  imported WordPress posts often had it). morlaca-valley 0.1.5 does the same on its own
  article page.

- **rating 0.1.0: visitors' votes on any module's records**, three kinds: stars (1–5:
  places and services), helpful (yes / no: articles, documentation) and up/down (entries,
  posts). A page embeds `{{ rating(subject, kind) }}`; the subject is signed in the form.
  One vote per visitor and subject, changeable (a necessary `nest_voter` cookie, set when
  voting, and a day's hash of the address and browser against cleared cookies; neither is
  kept raw); an average only from `min_votes` votes; schema.org AggregateRating where the
  page names what it rates. Admin: subjects lately rated (close, reset), visitors with many
  votes in a day (forget their votes).
- **coaches 0.1.3:** stars on each operator's page (transportul.ro).
- **content, glossary: a `rating` setting** (stars, helpful, updown, or none): every entry or
  term gets the rating module's widget above its comments. morlaca.ro and transilpedia.ro
  rate their articles and pages with stars, regionalisme.ro its terms (the morlaca-valley
  theme's own article page too).
- **transit 0.1.4: live delays carried on, live maps that follow the vehicles.**
  - The cities' live data (Bucharest, Cluj, Iași, Buzău) predicts a vehicle's next stops
    only (7 to 20). A stop further on now takes the delay of the last one predicted, as
    GTFS-realtime says; before, a late bus far away showed on time and vanished from the
    board at its timetable time though it had not come. A stop the bus has passed (every
    prediction further on) leaves the board.
  - On the live map each vehicle is shown where it should be now: its last heard place
    (30 s to 2 min old, as the city sends it) carried along its own route at the speed
    learned for that stretch, asked again every 8 seconds; before, it stood still until
    the source's next position, then jumped.
- **flights 0.1.6:** the radar's planes fly on from when their positions were taken, not
  from when the page got them (a snapshot 20 s old had them kilometres behind).
- **hub 0.1.4:** favourites move with ▲ and ▼ at their right (only where they can go),
  their names whole on one or two lines; the page's end (the footer, with the version) stays
  above the tabs.

## 0.4.6

- **What runs, in every footer:** after the Nest credit, the application and its version,
  Nest's, and the commits its image was built from ("gari 0.1.1 · Nest 0.4.6 ·
  c81f0c3-2db07e4"). nest-images bakes the commits into the image (`NEST_REVISION`); an
  application's image tag is its own version, raised with every change to it.
- **nest-core: calls between sites that run side by side** (`NEST_LOCAL_ROUTES`,
  `public-host=http://container:port`, comma separated): a module asking another of our
  sites goes straight to its container, saying the public host, so the answer and its links
  are the public ones; the public address only when that container is not there. The
  planner, the hub and the flights module's ground transport use it. The transport sites'
  services share one Docker network (`nest-transport`) and the list: faster (no trip out
  through Cloudflare and back), and Cloudflare's bot checks never see our own calls.
- **nest-core: the machine's own health checks** (Docker's, every 30 seconds, from
  127.0.0.1) are left out of the access log, in production (gunicorn) and with `nest run`;
  visitors' lines, and health checks from outside, stay.
- **trains 0.2.4, hub 0.1.2: their home pages print the seo module's head** (description,
  Open Graph, and on the site's home the Google and Bing verification codes). gari.ro's home
  is the trains module's: without it, Bing could not verify gari.ro.
- **push 0.1.0: notifications on a visitor's device (Web Push), for any module.** Any
  module schedules what to say and when (`push.schedule`); every 30 seconds what is due is
  sent, after the module looks again (its `recheck` lookup: move it, change it, drop it).
  VAPID and RFC 8291 encryption with the `cryptography` package only (checked against the
  RFC's own example). Kept: the browser's push address, sealed under the site's key, and
  what waits for it; deleted once sent, or when the push service says the address is gone.
  Only the browsers' own push services are posted to.
- **hub 0.1.1: reminders.** A bell on each departure of a place's board: a notification
  some minutes before it leaves (5 for a city stop, 15 for a train or coach, 3 hours for a
  flight; the visitor chooses), moved when the bus runs late, "cancelled" when the run is,
  and for a flight "in the air" once the radar sees it. Your reminders on the favourites
  page, each cancellable.
- **pwa 0.1.1:** the service worker shows notifications and opens their page on a tap; a
  site may recommend another app instead of installing itself (`app_url`, `app_name`,
  `app_text`): gari.ro, transport-comun.ro, transportul.ro and aeroportul.ro recommend
  Încotro? on phones, and link it in their footers.
- **hub 0.1.0: one transport app over the four sites** (Încotro?, app.transportul.ro):
  near me (city stops, train stations, coach stations, airports, each with its next
  departures), a place's board refreshed by itself (live times where the city publishes
  them), your places kept on the device (never on the server), the planner. The position
  is sent by POST and rounded to about 100 m before it reaches the sites; a board's address
  is built from a kind and a slug only. Its own API: `/api/v1/aproape`,
  `/api/v1/plecari/<kind>/<id>`.
- **The same "near me" and board API on every site:** `/api/v1/aproape` (now with `kind`,
  `id`, `board` on each place) and a board each - trains 0.2.3
  (`/api/v1/gara/<slug>/plecari`), transit 0.1.3 (`/api/v1/oras/<city>/statia/<stop>/plecari`,
  with live times and the vehicles coming), coaches 0.1.2 (`/api/v1/autogara/<slug>/plecari`),
  flights 0.1.4 (`/api/v1/aproape`, `/api/v1/aeroport/<slug>/plecari`, usual times, in the air
  now). Departures or arrivals (`sosiri=1`), from an hour (`ora`) for some hours (`ore`).

## 0.4.5

- **pwa 0.1.0: every site can be an installable web app** (and the base of an Android app).
  - `/manifest.webmanifest` with the theme's icons (192, 512, maskable) and colour, up to
    four shortcuts (the theme's menu by default); Chrome finds it installable.
  - `/sw.js`, the service worker: the offline page and the site's look kept at once;
    pages from the network, the copy kept when it fails (the newest 40), else the offline
    page listing what was kept. Never a signed-in visitor's page, the admin panel, the
    account pages or a POST. Files under /assets/ from the cache; maps (.geojson) their
    last copy; live data always from the network.
  - An install button (after the cookie choice; a hint on iPhone), "A new version is ready"
    with a Reload button, "You are offline: this page as it was on …".
  - `/.well-known/assetlinks.json` for the Android app (Bubblewrap) once its package and
    signing fingerprints are set.
  - On gari.ro, transport-comun.ro, transportul.ro and aeroportul.ro.
- **nest-core 0.4.5:** a signed-in visitor's pages are sent `Cache-Control: private,
  no-cache` (no cache keeps them, nor the service worker); the web app's addresses
  (/sw.js, /manifest.webmanifest, /offline, /.well-known/) are one each, whatever the
  visitor's language.
- **Themes base 0.2.5, paper 0.1.4, rail-signage 0.1.5, transit-lines 0.1.3:** their
  layouts include the web app's head and notices; rail-signage and transit-lines give
  their icons (PNG and maskable, per variant).

- **planner 0.1.1: along the roads, and the right station.**
  - Cars, taxis and walks follow the streets when a road router answers (Valhalla on
    your own server, the new `road_router` setting): their lengths and minutes from the
    roads, and the map draws them along the streets. None set, or it does not answer: a
    straight line as before. See [Road router](operate/road-router.md).
  - The first and last miles weigh a walk (up to 2.5 km) against the city's or county's
    buses, the minutes waiting for a bus and a change between buses counting; a taxi
    when nothing else gets there, or the buses would arrive 40 minutes later.
- **trains 0.2.2: a town's own station first.** The stations tried at each end are the
  town's own (within 3 km) first, then the nearest and the busiest within 12 km. A trip to
  Dej now ends at Dej Călători, at the town's edge, then on to the centre, never at Gherla
  and back.
- **flights 0.1.3: adsb.lol's Retry-After.** On a 429 (or 503) adsb.lol is not asked
  again, by any worker, for the seconds its Retry-After says (a minute when it says
  none, an hour at most): the radar uses OpenSky meanwhile when it has a client, else
  shows the last positions; route lookups wait too.

- **flights 0.1.2: a page per aircraft and per flight.**
  - **An aircraft** (`/avion/<ICAO address>`): its registration, maker, model and
    operator (hexdb.io), a photo from planespotters.net (photographer credited, linked
    as their terms ask), where it is now when the radar sees it, and its flights from and
    to our airports lately. Asked once, kept 45 days. The registered owner is never kept:
    for a private aircraft it may be a person.
  - **A flight** (`/zbor/<callsign>`): its routes with usual departure, arrival and
    weekdays, the aircraft seen on it, whether it is in the air now. Flights of the
    passenger airlines are in the sitemap.
  - Timetables link each flight; radar popups link the flight and the aircraft. The
    page policy allows planespotters' images (t.plnspttrs.net).

- **flights 0.1.1: airport timetables and readable radar planes.**
  - Each airport page has its usual departures and arrivals, today and tomorrow, from the
    flights seen in the last three weeks on that weekday (OpenSky; the import now fetches
    each airport's arrivals too, the flights from abroad). Shown as usual times,
    estimated; "în aer acum" when the plane is on the radar.
  - Flights to and from 3,949 airports with scheduled flights are named by their towns,
    in Romanian where Romanians say them otherwise (Londra Luton, Paris Beauvais, Viena).
  - A flight number as on a ticket only when its callsign says it (TAROM's ROT601: RO 601);
    a callsign with letters (Wizz Air's WMT7R) stays as it is.
  - Radar popups name the aircraft (Boeing 787-9, not B789) and more airlines. On a click
    they show the flight's route: from the flights seen, else adsb.lol's route lookup
    (counted in the day's budget, kept six hours).
  - Airport pages' search words mention departures and arrivals.

## 0.4.4

- **Caching, capped in size, for the transport sites' heavy work.**
  - **Încotro** keeps a search's options for 10 minutes (the same places within about
    100 m, day, quarter of an hour and modes), each site's answers by mode (city 2 min,
    trains and coaches 15, flights 60), and map paths for a day. All are settings.
  - Kept in the application's cache: Redis, shared and capped by its `maxmemory`; or the
    in-memory cache, per worker, now also capped in size (cache-memory 0.2.2: `max_mb`,
    default 8). Without one, in a cache of its own of at most 4 MB per worker. Compressed
    JSON, expiring by itself.
  - Admin → Încotro shows the cache and empties it: a new generation, so every worker
    stops seeing the old entries at once.
  - At most 20 searches a minute per address (a setting).
  - The search runs in a worker thread, the event loop free for the other visitors.
  - Day indexes: each worker builds today's ahead of time, every 15 minutes, so the
    first search of the day does not wait: transit's busiest cities (`warm_cities`, 2),
    trains, coaches. Days already past are dropped from memory at once.
  - The transport sites run 2 workers of 16 threads (was 3): fewer copies of the indexes
    in memory.

- **Secrets set in the admin panel (nest-core 0.4.4, admin 0.2.3).**
  - Any secret setting can be set in its module's settings in the admin panel: an API
    key, an API client's id and secret (adsb.lol, OpenSky, Tranzy, the planner's shared
    key).
  - Kept encrypted in the workspace's settings file (AES-GCM, under a key from the
    application's secret key, which stays in the environment).
  - Never shown again: the page says only whether one is set. Left empty it stays; "back
    to the default" removes it. A value the environment sets still wins.
- **Încotro: real ways on the map.** Trains follow their track (every point they pass, the
  stations they do not stop at too, from gari.ro); buses, trams and coaches follow their
  line's published path (GTFS shapes, from transport-comun.ro and transportul.ro, else stop
  by stop); planes are an arc; walks, cars and taxis stay straight. A trip keeps only a
  short reference per segment (its site, its trip): the map asks for the ways when it
  opens, so a shared link stays short. New: `/api/v1/traseu` on trains, transit and coaches,
  and the lookups `path.train`, `path.city`, `path.coach`; transit exports `ride_path`.
- **Încotro: a trip on the map, and shared.** Each option has "Pe hartă": its page draws every
  segment from where it starts to where it ends in its mode's colour, the places as dots.
  A trip's page sends its link through the phone's share menu (WhatsApp, Messenger, SMS,
  email), or a WhatsApp or email link; on a computer it copies the link. The link holds
  the whole trip, encrypted; nothing is stored.
- **Încotro:** the trips to and from a station or an airport 3 km away or more also take
  the county's buses (transportul.ro), beside the city's and a taxi. An address in a town
  whose streets are not indexed yet starts at the town's centre, said so.
- **flights:** the OpenSky import runs every 6 hours, asks only the days not yet asked,
  and stops politely at OpenSky's daily limit (429), going on at the next run. Usual
  timetables are gate to gate (15 minutes before the receivers see the flight airborne,
  10 after it lands), for the passenger airlines only.

- **Încotro: planes and street addresses.**
  - **Planes:** from the flights seen (OpenSky; the flights module imports the day before's
    departures from the airports each night, the last two weeks the first time) come the
    routes' usual timetables. The planner shows them as flights with estimated times,
    allowing 75 minutes at the airport before and 25 after.
  - **Addresses:** typed as people write them ("Erich Bergel 20 Cluj-Napoca", "Bd. 21
    Decembrie 1989 nr. 104, Cluj-Napoca"). The bigger towns' streets and house numbers
    come from OpenStreetMap (the streets job, monthly per town, gently) and are searched
    on the site; the house when OSM knows its number, else the street's middle.
  - The "only one means of transport" filter is gone: those options show anyway.

- **base 0.2.4: checkboxes and radio buttons one size everywhere.** The form fields'
  style (full width, padding, a minimum height) is for text fields, lists and text areas
  only. Checkboxes and radios are 1.1rem in the site's accent colour, beside their words,
  on the sites and in the admin panel. Before, those outside a few wrapper classes came
  out bigger.

- **Favicons for the transport sites:** transit-lines (a city bus for `lines`, a coach for
  `road`, a plane for `air`, each with its theme colour) and rail-signage 0.1.4 (a train in
  its signage blue and amber), as SVG; a theme built on them may replace the `icon` block.

- **planner 0.1.0** (new): **Încotro?**, the door-to-door journey planner of the four
  transport sites, the same on each (`/incotro`).
  - From a place to a place: a locality's centre (20,061 in Romania and Moldova, from
    GeoNames, searched offline), or the browser's position.
  - By every mode the sites know, each option's segments with their modes: trains
    (gari.ro), coaches (transportul.ro), city transport (transport-comun.ro), on foot, car,
    taxi.
  - Between towns, each train or coach journey gets a first and a last mile: a walk, the
    city's journey to the station, or a taxi.
  - Ranked by a score: time, waiting, price, changes and walking. Options another beats
    on every count are left out. Badges mark the best, the fastest, the cheapest and the
    direct ones. A "single means of transport" filter.
  - Nothing about a search is kept on the server: no rows, and searches are sent by POST.
  - A trip is kept only on the visitor's side:
    - in an AES-GCM encrypted cookie, when they allowed "preferences" (consent);
    - as a calendar file (an event per segment, with a reminder);
    - as text, a printable page, or an encrypted share link that any of the four sites
      opens (with the shared `vault_key`).
- **trains 0.2.1, coaches, transit:** `/api/v1/calatorie?de=lat,lon&la=lat,lon&data=&ora=`,
  journeys between two points in one shape (legs with mode, line, places, times, price),
  and the same as lookups (`journeys.train`, `journeys.coach`, `journeys.city`) for the
  planner on the same site.
- **consent 0.1.1:** the lookup `consent.allowed`, so other modules can check a purpose
  without importing consent.

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
