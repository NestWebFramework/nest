<!-- nest:readme -->
# Keeper

The deployed sites Nest watches through their agents, and Nest's applications, their plans and packages.

**Version 0.2.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-keeper` |
| name in a manifest | `keeper` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/keeper |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: keeper
    route: /keeper
```

## Settings

| setting | kind | default |
|---|---|---|
| `apps` | str | `applications` |
| `check_seconds` | int | `300` |
| `history_days` | int | `30` |
| `host_url` | str |  |
| `host_token` | str | *(secret)* |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
