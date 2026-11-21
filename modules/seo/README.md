<!-- nest:readme -->
# SEO

Search titles, descriptions, keywords, sharing pictures and indexing for every page of every module; meta tags, Open Graph and JSON-LD; a sitemap with photos; robots.txt.

**Version 0.1.0** · module · works with Nest `>=0.2,<1` · licence MIT

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

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
