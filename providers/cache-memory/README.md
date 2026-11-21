<!-- nest:readme -->
# Memory cache

Keeps values in the application's own memory: nothing to run, gone on restart, one process only. For development and small applications.

**Version 0.2.1** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-cache-memory` |
| name in a manifest | `cache-memory` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/providers/cache-memory |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.cache:
    providers: [cache-memory]
```

## Settings

| setting | kind | default |
|---|---|---|
| `max_items` | int | `10000` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
