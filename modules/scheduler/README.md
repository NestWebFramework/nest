<!-- nest:readme -->
# Scheduler

Jobs at set times or intervals, declared in the packages' manifests, run once across the workers.

**Version 0.1.1** · module · works with Nest `>=0.3,<1` · licence MIT

| | |
|---|---|
| package | `nest-scheduler` |
| name in a manifest | `scheduler` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/scheduler |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: scheduler
    route: /scheduler
```

## Settings

| setting | kind | default |
|---|---|---|
| `timezone` | str | `Europe/Bucharest` |
| `threads` | int | `4` |
| `history_days` | int | `30` |
| `lease_seconds` | int | `60` |
| `enabled` | bool | `True` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
