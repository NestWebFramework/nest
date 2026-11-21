<!-- nest:readme -->
# Registry

A registry of Nest packages, a Python package index for uv and pip, and a catalog of what each package is.

**Version 0.1.1** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-registry` |
| name in a manifest | `registry` |
| category | platform |
| reference | https://nest-framework.org/docs/reference/modules/registry |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: registry
    route: /registry
```

## Settings

| setting | kind | default |
|---|---|---|
| `public_url` | str |  |
| `publishers` | str | `approved` |
| `official_prefix` | str | `nest.` |
| `index_only` | str | `nest-core` |
| `require_signatures` | bool | `False` |
| `max_upload_mb` | int | `50` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
