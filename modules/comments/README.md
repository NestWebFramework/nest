<!-- nest:readme -->
# Comments

Threaded comments on any module's records, with moderation and spam defences.

**Version 0.1.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-comments` |
| name in a manifest | `comments` |
| category | community |
| reference | https://nest-framework.org/docs/reference/modules/comments |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: comments
    route: /comments
```

## Settings

| setting | kind | default |
|---|---|---|
| `allow_guests` | bool | `False` |
| `moderation` | str | `guests` |
| `max_depth` | int | `3` |
| `min_seconds` | float | `3` |
| `per_hour` | int | `10` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
