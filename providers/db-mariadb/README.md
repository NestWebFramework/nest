<!-- nest:readme -->
# MariaDB

MariaDB or MySQL through PyMySQL, utf8mb4, strict mode, UTC, pooled.

**Version 0.1.1** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-db-mariadb` |
| name in a manifest | `db-mariadb` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/providers/db-mariadb |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.db:
    providers: [db-mariadb]
```

## Settings

| setting | kind | default |
|---|---|---|
| `url` | str | *(secret)* |
| `host` | str | `127.0.0.1` |
| `port` | int | `3306` |
| `database` | str |  |
| `user` | str |  |
| `password` | str | *(secret)* |
| `flavour` | str | `mariadb` |
| `ssl_ca` | str |  |
| `pool_size` | int | `5` |
| `max_overflow` | int | `5` |
| `pool_recycle` | int | `280` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
