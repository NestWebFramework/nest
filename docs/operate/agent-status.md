---
title: "The agent's status format"
description: "What a service answers so a Nest keeper can watch it: one JSON document behind a bearer token. Nest sites answer it through the agent module; any other program can too."
---

# The agent's status format

A [keeper](keeper.md) watches a service by asking it one question, and the question is
simple to answer. A Nest site answers it through the `agent` module. Any other program can
answer it too, such as a RoboHub instance or a service in another language, and the keeper
then shows it the way it shows a Nest site.

A service that does not answer this format can still be watched with a **web check**: the
keeper asks its address and counts any answer below 400 as up. This format tells it much more.

This page describes version `1` of the format.

## The request

```http
GET {agent}/v1/status
Authorization: Bearer na_…
Accept: application/json
User-Agent: nest-keeper
```

`{agent}` is the address the keeper is given for the service: by default its address
followed by `/_agent`, as in `https://robohub.example/_agent`.

- The token is the only credential. Compare it in constant time, keep only its hash
  (SHA-256), and never read a cookie on these addresses.
- Answer `401` with `WWW-Authenticate: Bearer` for a missing or wrong token. Answering
  `429` to an address that keeps sending wrong ones is a good idea.
- Answer with `Cache-Control: no-store`.
- Serve it over https. The keeper sends a token in clear only to its own machine.
- The keeper waits at most 10 seconds for an answer, and follows no redirect.

Tokens start with `na_` followed by 43 random URL-safe characters (32 random bytes).
`nest agent token APP` makes one, and so can any other generator of the same shape: the
keeper only checks the `na_` prefix and the length (under 100 characters).

## The answer

`200` with a JSON object. Only `app` and `ok` are required. Every other field is optional,
and the keeper shows what it finds:

```json
{
  "agent": "1",
  "ok": true,
  "app": {"name": "robohub", "title": "RoboHub", "version": "2.4.0"},
  "uptime_s": 86400,
  "production": true,
  "requests": {"total": 18234, "errors": 2, "slow": 11, "last_error": "2026-11-20T09:14:02+00:00"},
  "checks": {"database": true, "queue": true},
  "migrations": {"pending": []},
  "backups": {"count": 14, "last": "robohub-20261120.tar.gz", "age_hours": 7.5, "size_mb": 120.4},
  "databases": [{"name": "robohub", "kind": "server"}],
  "disk": {"free_gb": 120.5, "total_gb": 200.0},
  "scope": "read"
}
```

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | **required**: the service is well. `false` shows the site as *needs care* |
| `app.name` | string | **required**: its name |
| `app.version` | string | its version, kept with each check |
| `app.title` | string | how it calls itself |
| `agent` | string | the format's version (`"1"`) |
| `nest`, `python` | string | the versions it runs on, if they apply |
| `uptime_s` | int | seconds since the process started |
| `production` | bool | `false` is shown as a warning |
| `requests` | object | `total`, `errors` (5xx), `slow` (over a second), `last_error` (ISO time) |
| `checks` | object | name → bool: what it depends on, each well or not. A `false` makes the keeper say which |
| `migrations.pending` | list | names behind their database migrations; the keeper names them |
| `degraded` | list | parts that failed to start |
| `backups` | object | `count`, `last`, `age_hours`, `size_mb` |
| `databases` | list | each `name`, `kind`, and `size_mb` if it is a file |
| `disk` | object | `free_gb`, `total_gb` |
| `scope` | string | `read` or `control`: what this token may do |

When `ok` is false, the keeper writes what it can tell from `migrations.pending`,
`degraded` and the failing `checks` as the site's problem.

## Optional: events and actions

A service may also answer these. The keeper's site page uses them when present:

| Call | Answer |
|---|---|
| `GET {agent}/v1/events?after=N` | `{"events": [{"id", "at", "level", "source", "text"}], "last": N}`: recent warnings and errors, newest last |
| `GET {agent}/v1/actions` | `{"actions": [{"name", "title", "description", "running"}], "allowed": bool}` |
| `POST {agent}/v1/actions/{name}` | with a control token: run it. `200 {"action", "ok", "seconds", "result"}`, `403` for a read token, `404` unknown, `409` already running |
| `GET {agent}/v1/check` | `{"failed": bool, "findings": [{"level": "ok"/"warn"/"fail", "text"}]}`: a production check |

## A minimal answer, in a few lines

A service in Python, behind its own framework, can answer the format this way:

```python
import hashlib, hmac, os

KEPT = os.environ["AGENT_READ_TOKEN_SHA256"]  # "sha256:…" from `nest agent token`

def status(request):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    digest = "sha256:" + hashlib.sha256(token.strip().encode()).hexdigest()
    if scheme.lower() != "bearer" or not hmac.compare_digest(digest, KEPT):
        return json_response({"error": "a valid token is needed"}, 401,
                             headers={"WWW-Authenticate": "Bearer"})
    return json_response({"ok": True, "app": {"name": "robohub", "version": VERSION}},
                         headers={"Cache-Control": "no-store"})
```
