<!-- nest:readme -->
# Near me

A near-me page every module with places contributes to; distances and a locate button.

**Version 0.1.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-geo` |
| name in a manifest | `geo` |
| category | maps |
| reference | https://nest-framework.org/docs/reference/modules/geo |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: geo
    route: /geo
```

## Settings

| setting | kind | default |
|---|---|---|
| `radius_km` | int | `50` |
| `limit` | int | `10` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
