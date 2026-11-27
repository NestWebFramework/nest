---
title: "Content and media"
description: "Pages, articles, categories, the editor and revisions with the content module; safe uploads with media; photo galleries; and maps with Leaflet."
---

# Content and media

Four modules hold what a site shows: `content` (pages and articles), `media` (stored
files), `gallery` (photos) and `maps` (places). Each is independent; they cooperate
through shortcodes and lookups, so a site takes only what it needs.

```yaml
modules:
  - name: content
    route: /
  - name: media
    route: /media
  - name: gallery
    route: /galerii-foto
  - name: maps
    route: /harti

bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
  nest.storage: {providers: [storage-local]}
```

## Content

`content` is the CMS. It combines content types with custom fields (as Geticus had)
with WordPress's posts, pages and taxonomies. It must be mounted at `/`, because its
pages live at whole-site addresses.

### Entries, pages and content types

Everything is an **entry** of a **content type**. Out of the box there are
WordPress's two:

| Type | Address | Notes |
|---|---|---|
| `post` | `/{category}/{slug}/` | Categories and tags |
| `page` | `/{path}/` | Hierarchical: a child page's address follows its parent's |

Content types and taxonomies are declared in YAML, by any package or by the
application, and the application's declarations win. An event type with custom
fields:

```yaml
content_types:
  event:
    title: Events
    path: "/events/{year}/{slug}/"
    taxonomies: [category]
    fields:
      starts: {type: datetime, label: Starts, required: true}
      kind:   {type: select, choices: [fair, feast]}
```

Field types are `text`, `textarea`, `html`, `integer`, `decimal`, `boolean`, `date`,
`datetime`, `select`, `url`, `media` and `entry`. Each entry keeps its fields as
JSON, checked against the declaration, so adding a field needs no migration.
`uv run nest content types APP` lists what an application has.

### Addresses

An entry's address is made from its type's path template and **stored**. A request
that matches no route is looked up by its path, so a moved site keeps every URL.
When an editor changes a slug, the old address is recorded with the `redirects`
module, if the site has it, so old links keep working.

### Categories and tags

Taxonomies (`category`, `post_tag`, or your own) have their own addresses
(`/category/{path}/`, `/tag/{slug}/`) and their own pages in the admin panel under
Content. A hierarchical taxonomy has parents and children.

### Menus

Menus are stored by the content module and drawn by the theme; the WordPress and
Geticus importers bring a site's menu over. **Content → Menus** manages them: a menu is
made, renamed or deleted; its links lead to a page or an article, a category, a module's
pages (each module that offers one) or any address, and are renamed, moved up and down,
put under another link or out of it, opened in a new window, removed. A link to a page
with no label of its own shows the page's title, in every language; a label of its own is
translated in Translations. The theme says which menus it shows (`menus:` in its
manifest, `main` in Nest's themes): a menu with that address is shown there. A theme with a **Menu** setting of its own (its
links, set in Settings → Themes or in `application.theme_settings`) shows that instead.

### The editor

Editors (the `editor` role) work at **Admin → Content**. The body is written in a
rich-text editor (Tiptap), with pictures uploaded in place. Bodies are HTML,
**sanitized on every save** (with nh3), so an editor cannot store a script.
Shortcodes such as `[gallery slug="..."]` are expanded only when a page is shown,
and only in text.

| Setting | Default | Meaning |
|---|---|---|
| `home` | empty | The path of the entry shown at `/`; empty shows the latest entries |
| `per_page` | 10 | Entries per listing page |
| `media_max_mb` | 10 | The largest picture an editor may upload, in MB |
| `trash_days` | 30 | How long a deleted entry waits in the trash (0 keeps it) |
| `site_url` | empty | The public address, for the sitemap, the feed and shared links |

### Revisions and the trash

Every save keeps a **revision**. An entry's versions can be opened, compared with the
current text, and restored. A deleted entry goes to the **trash**, where it can be
restored or purged; after `trash_days` it is deleted for good.

### Imports

A WordPress site moves in from its mysqldump and uploads folder; no MySQL server is
needed:

```sh
uv run nest content import-wordpress ../mysite ~/legacy/mysite.sql \
    --uploads ~/legacy/wp-content/uploads
```

It brings categories and tags, posts and pages with their slugs, featured images and
attachments, menus and the static front page. Old `?p=123` links redirect, and links
to the old site's uploads become `/media/uploads/...`.

A Geticus site's pages come in the same way:

```sh
uv run nest content import-geticus ../mysite ~/legacy/mysite.sql --root ~/legacy/mysite
```

Both are safe to run again: what they brought before is updated, not duplicated.
Comments and galleries come in through their own modules (`nest comments
import-wordpress`, `nest gallery import-wordpress`).

## Media and uploads

`media` serves the files kept in `nest.storage` at its route (`/media` by convention).
Templates get `media_url(key)` and `media_srcset(key)`; pictures are served at the
widths pages need (320, 640, 960, 1280 and 1920 pixels).

### Why uploads are safe

Every picture an editor uploads, to content or to a gallery, goes through
`clean_image`:

- **Checked by its bytes**, not its name: only JPEG, PNG, WebP and GIF.
- **Read whole** with Pillow, so a file that only starts like a picture (a
  "polyglot"), or a broken one, is refused.
- **Size-limited**: a picture over 50 million pixels is refused (a decompression
  bomb is small on disk and enormous once decoded), and each module caps the file
  size (`media_max_mb` for content, `upload_max_mb` for galleries).
- **Written again** without its metadata: no GPS position, camera or time from a
  phone. It is turned upright as the camera said, and its colour profile is kept.

A stored HTML or SVG file is sent as a sandboxed attachment, never shown as a page,
so a stored file cannot run script on the site. The application also caps the size
of any request body (`application.max_body_mb`, 32 by default).

## Gallery

`gallery` holds photo **galleries**; an **album** is a gallery of galleries. Each has
its own page under the module's route, and photos open in a lightbox (a small static
script; without JavaScript they are plain links).

At **Admin → Galleries** editors:

- create galleries and albums and move a gallery into an album;
- upload photos, one or many at a time, with progress shown;
- write each photo's caption and alternative text, choose the cover;
- reorder photos (each row moves up or down) and remove them;
- publish or hide a gallery.

| Setting | Default | Meaning |
|---|---|---|
| `upload_max_mb` | 15 | The largest photo an editor may upload, in MB |
| `index` | true | Whether the module's route lists every top-level album and gallery. Turn it off when a page of the site lives at that address. |

With `content`, pages embed galleries with `[gallery slug="..."]` and
`[album slug="..."]`. The importers bring Photo Gallery (10Web) and NextGEN galleries
from WordPress, and Geticus galleries, and keep the plugins' ids, so
`[nggallery id=1]` in imported pages keeps working.

```sh
uv run nest gallery import-wordpress ../mysite ~/legacy/mysite.sql --uploads ~/legacy/wp-content/uploads
uv run nest gallery list ../mysite
uv run nest gallery tidy ../mysite     # clear descriptions that are file names or camera data
```

## Maps

`maps` draws maps with markers using Leaflet, which ships with the module (nothing
loaded from a CDN). Maps and markers are edited at **Admin → Maps**. Each map has a
page under the module's route and a GeoJSON file (`<route>/<slug>.geojson`); a page
embeds one with `[map slug="..."]`, and WordPress's `[wpgmza id="1"]` still works after
`nest maps import-wordpress`.

The module's own page shows the main map with every place the application's modules
offer: any module answers the `map.points` lookup with its places (content does, for
entries with coordinates).

### Tile providers

The map's pictures (tiles) come from a provider, chosen in Settings → Maps:

| Setting | Meaning |
|---|---|
| `provider` | `osm` (default), `opentopomap`, `maptiler`, `thunderforest`, `stadia` or `custom` |
| `api_key` | The provider's key for MapTiler, Thunderforest or Stadia Maps |
| `style` | The provider's style, such as MapTiler `outdoor-v2`; empty for its usual one |
| `tiles` | For `custom`: an https address with `{z}`, `{x}`, `{y}` and `{key}` |
| `attribution` | Who to credit under the map; empty takes the provider's own |
| `max_zoom` | How close readers may zoom (1-20); 0 takes the provider's limit |
| `main` | The slug of the map the module's page shows; empty takes the first |

OpenStreetMap and OpenTopoMap need no key, for light use. A provider's key is not a
secret (the browser sees it in every tile address): limit it to your domain in the
provider's account. The page's Content-Security-Policy lets in only the chosen
provider's tile host.

### A map on another module's page

A module that has its own data can put a map on its page without depending on
`maps`, through the `maps.element` lookup. A hypothetical module `example`, on the page
of one of its places:

```python
nest = request.app.state.nest
if nest.answered("maps.element"):
    place_map = nest.lookup("maps.element", {
        "request": request,
        "data": f"/example/{slug}/harta.geojson",    # its own GeoJSON
        "lat": 46.78, "lng": 23.59, "zoom": 14,
        "title": "Cluj Napoca",
        "fit": False,
    })
```

Without the maps module, the lookup has no answer and the page simply shows no map.
See [Lookups](../develop/lookups.md).
