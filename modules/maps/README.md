<!-- nest:readme -->
# Maps

Maps with markers (Leaflet, OpenStreetMap tiles), a page with every place the site's modules know, [map] and WordPress's [wpgmza] shortcodes, GeoJSON, an editor in the admin panel, and an importer for WP Google Maps.

**Version 0.2.1** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-maps` |
| name in a manifest | `maps` |
| category | maps |
| reference | https://nest-framework.org/docs/reference/modules/maps |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: maps
    route: /maps
```

## Settings

| setting | kind | default |
|---|---|---|
| `provider` | str | `osm` |
| `api_key` | str |  |
| `style` | str |  |
| `tiles` | str |  |
| `attribution` | str |  |
| `max_zoom` | int | `0` |
| `main` | str |  |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
