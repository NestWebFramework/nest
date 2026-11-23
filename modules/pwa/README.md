<!-- nest:readme -->
# Web app (PWA)

Installable web app - manifest, offline pages, install button, updates, Android app links.

**Version 0.1.0** · module · works with Nest `>=0.4.5,<1` · licence MIT

| | |
|---|---|
| package | `nest-pwa` |
| name in a manifest | `pwa` |
| category | platform |
| reference | https://nest-framework.org/docs/reference/modules/pwa |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: pwa
    route: /pwa
```

## Settings

| setting | kind | default |
|---|---|---|
| `name` | str |  |
| `short_name` | str |  |
| `description` | str |  |
| `theme_color` | str |  |
| `background_color` | str | `#ffffff` |
| `start_url` | str | `/` |
| `shortcuts` | str |  |
| `categories` | str |  |
| `offline_pages` | int | `40` |
| `install_button` | bool | `True` |
| `android_package` | str |  |
| `android_fingerprints` | str |  |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
## What it does

Makes a site an installable web app, and the base of an Android app (a Trusted Web
Activity, built with Google's Bubblewrap):

- **`/manifest.webmanifest`**: the name, colours, icons (from the theme in use) and up to
  four shortcuts (the theme's menu by default).
- **`/sw.js`**, the service worker:
  - keeps the offline page and the files every page needs when it starts;
  - pages from the network; when it fails, the copy kept, else the offline page. Every
    page for anyone is kept, the newest `offline_pages`; never one marked
    `Cache-Control: private` or `no-store` (Nest marks a signed-in visitor's pages
    private), never the admin panel, the account pages, anything but GET;
  - the site's files (`/assets/`, versioned) from the cache first; maps (`.geojson`) the
    last copy when offline; live data always from the network.
- **`/offline`**: shown when a page is asked offline and no copy was kept; lists the pages
  kept on the device.
- **An install button** when the browser offers to install (dismissed for 30 days with
  its ×), a hint on iPhone; **"A new version is ready"** with a Reload button; **"You are
  offline"**, and the date of a kept copy.
- **`/.well-known/assetlinks.json`** once `android_package` and `android_fingerprints` are
  set: the Android app then opens the site full screen, without the browser's bar.

## Icons from the theme

A theme's `module.yml` may give its icons (files of its `static/`), per value of its
`variant` setting or `default`:

```yaml
pwa:
  icons:
    default: {svg: icon.svg, png192: icon-192.png, png512: icon-512.png, maskable: icon-maskable.png, color: "#12355b"}
```

The maskable icon fills the whole square with the background, the drawing inside the
middle 80%: Android cuts it to a circle or a rounded square. Without a `pwa:` section, this
module's own icons.

## The layouts

A theme's layout includes `pwa/head.html` at the end of its `<head>` and `pwa/body.html`
at the end of its `<body>` (both `ignore missing`): base, paper, rail-signage and
transit-lines do.
