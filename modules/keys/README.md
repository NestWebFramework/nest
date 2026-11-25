<!-- nest:readme -->
# Keys and devices

Accounts without email or password - kept by a passkey or a downloaded key, on any device.

**Version 0.2.0** · module · works with Nest `>=0.4.7,<1` · licence MIT

| | |
|---|---|
| package | `nest-keys` |
| name in a manifest | `keys` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/keys |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: keys
    route: /keys
```

## Settings

| setting | kind | default |
|---|---|---|
| `play` | str | `/` |
| `after` | str | `/` |
| `device_days` | int | `365` |
| `new_accounts_per_day` | int | `3` |
| `unprotected_days` | int | `14` |
| `inactive_days` | int | `365` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
