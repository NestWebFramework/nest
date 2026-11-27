<!-- nest:readme -->
# Content

Pages, posts and any declared content type with custom fields; categories and tags; menus; media in nest.storage; revisions; search; a WordPress importer that keeps the old addresses.

**Version 0.2.7** · module · works with Nest `>=0.4,<1` · licence MIT

| | |
|---|---|
| package | `nest-content` |
| name in a manifest | `content` |
| category | content |
| reference | https://nest-framework.org/docs/reference/modules/content |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: content
    route: /content
```

## Settings

| setting | kind | default |
|---|---|---|
| `pictures_open_large` | bool | `False` |
| `rating` | str |  |
| `home` | str |  |
| `per_page` | int | `10` |
| `media_max_mb` | int | `10` |
| `trash_days` | int | `30` |
| `site_url` | str |  |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
