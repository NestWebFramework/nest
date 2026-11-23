<!-- nest:readme -->
# Push notifications

Notifications on a visitor's device (Web Push) - scheduled by any module, rechecked before sending, nothing kept after.

**Version 0.1.0** · module · works with Nest `>=0.4.5,<1` · licence MIT

| | |
|---|---|
| package | `nest-push` |
| name in a manifest | `push` |
| category | platform |
| reference | https://nest-framework.org/docs/reference/modules/push |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: push
    route: /push
```

## Settings

| setting | kind | default |
|---|---|---|
| `contact` | str |  |
| `per_address` | int | `20` |
| `forget_days` | int | `30` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
## What it does

Notifications on a visitor's phone or computer (Web Push), for any module of the site:

1. The page asks the browser for permission and a subscription
   (`PushManager.subscribe`, with the key from `<route>/cheie`) and gives it to the site
   (`POST <route>/abonare`).
2. A module schedules what to say and when (`push.schedule`), with the browser's endpoint.
3. Every 30 seconds what is due is sent. Just before, the module may look again (its
   `recheck` lookup): move it (a bus running late), change it, or drop it.

The site's service worker shows it (the pwa module's worker handles `push` and
`notificationclick`: a tap opens the notification's `url`).

## What is kept

- The browser's push address (endpoint and keys), sealed under the site's key: no name, no
  account. Found by a hash of the endpoint, which the browser sends in a POST body.
- What is scheduled for it. A notification is deleted once sent; an address the push
  service says is gone, or with nothing scheduled for `forget_days`, is deleted.
- Only the browsers' own push services are posted to (Google, Mozilla, Apple, Microsoft).

## The protocol

VAPID (RFC 8292, ES256) and aes128gcm message encryption (RFC 8291), with the
`cryptography` package only. The site's key pair is made at the first start in the
workspace (`data/push/vapid.pem`); keep it with the backups.
