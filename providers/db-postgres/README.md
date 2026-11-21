<!-- nest:readme -->
# PostgreSQL

PostgreSQL through psycopg 3, pooled, in UTC, with TLS modes and a statement timeout.

**Version 0.1.0** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-db-postgres` |
| name in a manifest | `db-postgres` |
| reference | https://nest-framework.org/docs/reference/providers/db-postgres |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.db:
    providers: [db-postgres]
```

## Settings

| setting | kind | default |
|---|---|---|
| `url` | str | *(secret)* |
| `host` | str | `127.0.0.1` |
| `port` | int | `5432` |
| `database` | str |  |
| `user` | str |  |
| `password` | str | *(secret)* |
| `sslmode` | str | `prefer` |
| `pool_size` | int | `5` |
| `max_overflow` | int | `5` |
| `pool_timeout` | int | `30` |
| `statement_timeout_ms` | int | `0` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
