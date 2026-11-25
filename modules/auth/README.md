<!-- nest:readme -->
# Accounts

Accounts with roles, sign-in and sign-out, server-side sessions on the bound database, and the dependencies other modules protect routes with.

**Version 0.5.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-auth` |
| name in a manifest | `auth` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/auth |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: auth
    route: /auth
```

## Settings

| setting | kind | default |
|---|---|---|
| `after_register` | str | `/` |
| `allow_registration` | bool | `False` |
| `session_days` | int | `14` |
| `min_password_length` | int | `10` |
| `login_attempts` | int | `5` |
| `lockout_minutes` | int | `15` |
| `account_attempts` | int | `3` |
| `address_attempts` | int | `20` |
| `registrations_per_hour` | int | `5` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
