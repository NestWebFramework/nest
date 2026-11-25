<!-- nest:readme -->
# Keys and devices

Accounts without email or password - a device's session, the account's key (a link), passkeys, a device PIN, adding devices.

**Version 0.1.0** · module · works with Nest `>=0.4.7,<1` · licence MIT

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
| `pin_idle_hours` | float | `12` |
| `new_accounts_per_day` | int | `3` |
| `unprotected_days` | int | `14` |
| `inactive_days` | int | `365` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
