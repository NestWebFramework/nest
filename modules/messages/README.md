<!-- nest:readme -->
# Messages

Private conversations between members, with read state and live delivery.

**Version 0.1.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-messages` |
| name in a manifest | `messages` |
| category | community |
| reference | https://nest-framework.org/docs/reference/modules/messages |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: messages
    route: /messages
```

## Settings

| setting | kind | default |
|---|---|---|
| `max_recipients` | int | `10` |
| `per_hour` | int | `60` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
