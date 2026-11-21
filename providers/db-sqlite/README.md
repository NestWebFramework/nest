<!-- nest:readme -->
# SQLite

SQLite in the application's workspace, with WAL and foreign keys on.

**Version 0.1.1** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-db-sqlite` |
| name in a manifest | `db-sqlite` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/providers/db-sqlite |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.db:
    providers: [db-sqlite]
```

## Settings

| setting | kind | default |
|---|---|---|
| `path` | str | `data/app.db` |
| `journal_mode` | str | `WAL` |
| `synchronous` | str | `NORMAL` |
| `one_at_a_time` | bool | `True` |
| `busy_timeout_ms` | int | `5000` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
