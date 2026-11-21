<!-- nest:readme -->
# Documentation

Markdown documentation with a menu, search, pictures and a reference made from every package's manifest.

**Version 0.1.1** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-docs` |
| name in a manifest | `docs` |
| category | content |
| reference | https://nest-framework.org/docs/reference/modules/docs |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: docs
    route: /docs
```

## Settings

| setting | kind | default |
|---|---|---|
| `tree` | str | `docs` |
| `home` | bool | `False` |
| `reference` | bool | `True` |
| `reload` | bool | `False` |
| `nav` | str |  |
| `edit_url` | str |  |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
