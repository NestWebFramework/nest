---
title: "Security"
description: "What Nest does for every module without asking: CSRF, a strict content security policy, signed values, secrets, request limits, safe uploads, allowed hosts and proxies, and how modules keep robots out."
---

# Security

Nest's defaults are safe without a module asking for them: every response gets strict
headers, every unsafe request to a module's routes is checked for forgery, every request
body is limited before it is read. A module loosens one of these only by name, for one
response or one source, never for the whole site.

## What every response gets

`SecurityMiddleware` (in `nest/security.py`) wraps the whole application, so these
headers are set whatever a module did:

| Header | Value |
|---|---|
| `Content-Security-Policy` | the page policy below |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `same-origin` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains`, in production |

A header the module set itself is kept.

## CSRF

Every router mounted with `host.mount`, `host.admin` or `host.serve_at_root` gets the
`csrf_protect` dependency. A safe request (GET, HEAD, OPTIONS, TRACE) passes; any other
must:

1. come from this site, when it sends an `Origin`: the request's `Host`, the
   `X-Forwarded-Host` a proxy passed, or a name in `NEST_ALLOWED_HOSTS`;
2. carry a valid `nest_csrf` cookie (an HttpOnly, SameSite=Lax cookie holding a signed
   token);
3. send the same token back, in the `X-CSRF-Token` header or the `csrf_token` form
   field, compared in constant time.

Otherwise it is refused with 403. In a template, a form carries the field:

```jinja
<form method="post" action="{{ action }}/new">
  {{ csrf_field }}
  <button type="submit">{{ _("New word") }}</button>
</form>
```

and the base theme sends the header with every htmx request of a signed-in user or in the
admin panel (`hx-headers` with `{{ csrf_token }}`). A script that uploads sends the header,
so its body is not read to find the token.

The cookie is set only by a page that writes the token. A reader's page that holds no
form gets no cookie and, answered 200 to someone not signed in, is marked
`Cache-Control: public, max-age=60, stale-while-revalidate=300`: a proxy can cache it.

> [!WARNING]
> `host.mount(router, csrf=False)` is only for an API whose clients send a bearer token on
> every request, never a cookie (the registry's uploads). A browser's forged request
> carries no token, so there is nothing to forge.

When a handler reads a form itself, it says how much it accepts, as Nest's modules do:

```python
form = await request.form(max_files=0, max_fields=5)
```

When `csrf_protect` reads a form to find the token, it accepts at most 50 files and 500
fields.

## The content security policy

The default policy allows nothing from other origins, no inline script and no eval:

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self';
form-action 'self'; frame-ancestors 'none'
```

So a module's scripts are files linked with `asset()`, and its styles are in its
stylesheets, never in `style=""` or `<script>` blocks.

A package that needs another origin adds it in a top-level `csp:` section of its
`module.yml`. Only `img-src`, `frame-src`, `media-src` and `connect-src` may be extended,
and only with https sources (a host, optionally a path); a bare wildcard, a keyword or a
plain-http source stops the start. Scripts and styles stay `'self'`, so no package can
loosen what runs on a page.

```yaml
csp:
  frame-src: [https://www.youtube-nocookie.com]
```

A source chosen while the site runs (a map's tile server, set in the admin panel) is
added with `host.allow_source(directive, source, slot="")`. It is checked as a manifest's
is, and one per module and slot is kept, so a changed setting does not leave the old host
open.

### Loosening one response

`nest.security.allow(response, ...)` loosens the policy for one response, by name:

| Name | Effect |
|---|---|
| `"embed"` | other sites may show the page in a frame: no `X-Frame-Options`, `frame-ancestors *` (a widget, a station board) |
| `"geolocation"` | the page may ask the browser where the reader is: `geolocation=(self)` |

The geo module's near-me page is the only page of a site that may ask for the location:

```python
from nest.security import allow


@router.get("/")
def page(request: Request, lat: str = "", lon: str = ""):
    response = render(request, "geo/near.html", point=point, groups=groups)
    return allow(response, "geolocation")
```

## Redirects to local paths only

A `next=` parameter is how a phishing link borrows a site's trust. `local_path(value,
fallback="/")` (from `nest`) returns the value only when it is a path on this site; `//`,
a backslash, a control character or another host falls back.

## Signed values

`host.sign(value)` returns the value with an HMAC-SHA256 signature; `host.unsign(token)`
returns the value, or `None` when it was changed. The key is derived from the
application's secret and the module's name, so what one module signs another cannot pass
off as its own. Hangman keeps a whole game in a signed cookie (no table, nothing to clean
up), set HttpOnly, SameSite=Lax and Secure over https:

```python
response.set_cookie(
    COOKIE,
    game.dump(state["sign"]),
    max_age=60 * 60 * 24 * 365,
    httponly=True,
    samesite="lax",
    secure=request.url.scheme == "https",
    path=state["url"] or "/",
)
```

A signature proves a value was not changed, not that it is secret: never sign what the
visitor must not read.

## Secrets

| Secret | Where it comes from |
|---|---|
| the application key | `NEST_SECRET_KEY`, at least 32 characters, required when `NEST_ENV=production`; in development one is generated in the workspace's `data/secret.key` (mode 600) |
| a setting declared `secret: true` | the environment only (`NEST_<APP>__<OWNER>__<KEY>`): a manifest that sets it, or the admin panel, is refused, and it cannot have a default |

The workspace's `.env` file is read under the process environment (the process wins), so
secrets stay out of the repository.

## Request bodies and uploads

`BodyLimit` (in `nest/limits.py`) sits outside everything that reads a body: a request that says it is larger
than the limit (`Content-Length`) is refused with 413 before a byte is read; one that does
not say (chunked) is counted as it comes and stopped at the limit. The limit is
`application.max_body_mb` (32 by default); `NEST_MAX_BODY_MB` wins.

An uploaded picture goes through the media module's `clean_image(data)` before it is
kept (the gallery calls it for every photo). It is read whole with Pillow, so a file
that only starts like a picture, or a broken one, is refused, and so is one larger than
50 million pixels (a decompression bomb). It is then written again: turned upright as
its camera said, without its EXIF and XMP metadata (the place it was taken, the camera),
its colour profile kept.

## Hosts and proxies

| Setting | Effect |
|---|---|
| `NEST_ALLOWED_HOSTS` | comma-separated names the site answers to; any other `Host` is refused with 400 (`localhost` and `127.0.0.1` stay allowed for health checks) |
| `nest serve --forwarded-allow-ips` or `NEST_TRUSTED_PROXIES` | the proxies whose `X-Forwarded-*` headers are believed (default `127.0.0.1`) |

The health page `/_nest/health` answers only local requests in production; the API
documentation (`/_nest/docs`) exists only in development. See [deploy](../deploy.md).

## Sign-in limits

The auth module counts failed sign-ins per email and address (`login_attempts`, 5 by
default) and pauses that pair for `lockout_minutes` (15). The count lives where every
worker sees it: the shared cache when the application binds one every worker shares
(redis), otherwise the database, never one process's memory. The key is hashed: neither
table nor cache holds an email or an address.

## Keeping robots out of public forms

Modules that take text from visitors who have not signed in (comments, the glossary's
proposals) combine three cheap checks:

- a **honeypot**: a field people cannot see and robots fill in; a form with it filled is
  thanked and dropped;
- a **time stamp**: the time the form was shown, signed with the application's secret;
  a form sent back sooner than a setting (`min_seconds`, `proposals_min_seconds`) or after
  a day is refused;
- a **limit per address** per hour, the address kept only as a keyed hash.

```python
if str(form.get("website", "")):  # the honeypot: people cannot see it, robots fill it
    return _propose_page(request, db, {}, sent=True)
age = service.stamp_age(nest.secret, str(form.get("stamp", "")))
if age is None or age < float(_setting(request, "proposals_min_seconds")) or age > 86400:
    return again(t("That was quick. Please send it again."))
```

These are a module's own code, not a host facility: copy the pattern from
`nest_comments` or `nest_glossary`.
