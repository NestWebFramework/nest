<!-- nest:readme -->
# Redis

Redis or Valkey through redis-py's asyncio client, shared by every worker.

**Version 0.1.0** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-redis` |
| name in a manifest | `redis` |
| reference | https://nest-framework.org/docs/reference/providers/redis |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.cache:
    providers: [redis]
```

## Settings

| setting | kind | default |
|---|---|---|
| `url` | str | *(secret)* |
| `prefix` | str |  |
| `timeout` | float | `2.0` |
| `max_connections` | int | `20` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
