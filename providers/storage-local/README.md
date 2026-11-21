<!-- nest:readme -->
# Local storage

Files in a folder of the application's workspace (media/ by default).

**Version 0.1.0** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-storage-local` |
| name in a manifest | `storage-local` |
| reference | https://nest-framework.org/docs/reference/providers/storage-local |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.storage:
    providers: [storage-local]
```

## Settings

| setting | kind | default |
|---|---|---|
| `root` | str | `media` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
