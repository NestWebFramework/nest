<!-- nest:readme -->
# Cookies and consent

Every module's cookies declared, one notice asking only for what needs consent, a cookies page.

**Version 0.1.1** · module · works with Nest `>=0.4,<1` · licence MIT

| | |
|---|---|
| package | `nest-consent` |
| name in a manifest | `consent` |
| category | admin |
| reference | https://nest-framework.org/docs/reference/modules/consent |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: consent
    route: /consent
```

## Settings

| setting | kind | default |
|---|---|---|
| `days` | int | `180` |
| `notice` | str |  |
| `policy` | str |  |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
## How a module uses it

**Declare** the cookies it sets as it is configured now, by answering `consent.cookies`:

```python
host.answer(
    "consent.cookies",
    lambda _key: [
        {
            "name": "_ga",
            "purpose": "statistics",
            "duration": "2 years",
            "provider": "Google Analytics",
            "service": "google-analytics",
            "description": "Helps us see which pages are useful, so we can make the site better.",
        },
    ],
)
```

- `purpose` is one of `necessary` (set without asking), `preferences`, `statistics` or
  `marketing` (asked for).
- `service` groups cookies a visitor allows or refuses together (default: the module). The
  cookies page shows one switch per service only when a purpose has more than one.

**Ask** before setting one that needs consent:
- in a template: `consent().allowed("statistics", "google-analytics")`;
- in Python: `nest_consent.allowed(request, "statistics")`;
- in a page's script: `window.nestConsent.allowed("statistics")`.

Nest's own cookies (`nest_csrf`, `nest_locale`, the auth session, the admin panel's) are
declared by this module. The notice is in plain words: what the cookies are for, never who
sets them. Its buttons are OK, Only the essential and Choose (a switch per purpose). The
cookies page lists every cookie, who sets it and for how long. When a module adds a cookie
that needs consent, the visitor is asked again. The themes include the notice
(`consent/banner.html`).
