<!-- nest:readme -->
# Agent

The site's status, events and checks, and the actions it allows, for the keeper, to a token.

**Version 0.1.1** · module · works with Nest `>=0.3,<1` · licence MIT

| | |
|---|---|
| package | `nest-agent` |
| name in a manifest | `agent` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/agent |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: agent
    route: /agent
```

## Settings

| setting | kind | default |
|---|---|---|
| `read_token` | str | *(secret)* |
| `control_token` | str | *(secret)* |
| `backup_keep` | int | `7` |
| `events` | int | `200` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
