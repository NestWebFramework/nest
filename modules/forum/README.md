<!-- nest:readme -->
# Forum

Boards, topics and posts with moderation, editing, and replies that arrive live.

**Version 0.1.0** · module · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-forum` |
| name in a manifest | `forum` |
| category | community |
| reference | https://nest-framework.org/docs/reference/modules/forum |

## Using it

In an application's `module.yml`:

```yaml
modules:
  - name: forum
    route: /forum
```

## Settings

| setting | kind | default |
|---|---|---|
| `public_read` | bool | `True` |
| `edit_minutes` | int | `30` |
| `posts_per_page` | int | `30` |
| `topics_per_page` | int | `30` |
| `posts_per_minute` | int | `5` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
