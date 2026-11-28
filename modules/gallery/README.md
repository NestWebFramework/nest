<!-- nest:readme -->
# Galleries

Photo galleries and albums with pages, embeds, a lightbox, uploads in the admin panel and WordPress imports.

**Version 0.3.4** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-gallery` |
| name in a manifest | `gallery` |
| category | media |
| reference | https://nest-framework.org/docs/reference/modules/gallery |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: gallery
    route: /gallery
```

## Settings

| setting | kind | default |
|---|---|---|
| `upload_max_mb` | int | `15` |
| `index` | bool | `True` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
