<!-- nest:readme -->
# SEO

Search titles, descriptions, keywords, sharing pictures and indexing for every page of every module; meta tags, Open Graph and JSON-LD; a sitemap with photos; robots.txt.

**Version 0.2.0** · module · works with Nest `>=0.4.1,<1` · licence MIT

| | |
|---|---|
| package | `nest-seo` |
| name in a manifest | `seo` |
| category | seo |
| reference | https://nest-framework.org/docs/reference/modules/seo |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: seo
    route: /seo
```

## Settings

| setting | kind | default |
|---|---|---|
| `site_url` | str |  |
| `title_pattern` | str | `{title} · {site}` |
| `description` | str |  |
| `keywords` | str |  |
| `image` | str |  |
| `twitter` | str |  |
| `google_verification` | str |  |
| `bing_verification` | str |  |
| `robots_closed` | str |  |
| `google_analytics` | str |  |
| `analytics_consent` | bool | `true` |

What each does: the reference page, or the admin panel's Settings.

### Google Analytics

Set `google_analytics` to the GA4 measurement ID (`G-XXXXXXXXXX`, from Analytics → Admin →
Data streams → the web stream). Every public page then loads Google's tag (`gtag.js`),
never the admin panel. With `analytics_consent` on (the default), a visitor is asked first
and nothing is sent to Google until they agree; IPs are anonymized. Google's tag server is
the one outside script source Nest's core lets in (see Security), and only while an ID is
set. `google_verification` is something else: Search Console's ownership meta tag.
<!-- /nest:readme -->
