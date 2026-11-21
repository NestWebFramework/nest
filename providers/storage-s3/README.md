<!-- nest:readme -->
# S3 storage

Files in an S3-compatible object store (MinIO, Ceph, AWS S3), shared by every worker and machine.

**Version 0.1.1** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-storage-s3` |
| name in a manifest | `storage-s3` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/providers/storage-s3 |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.storage:
    providers: [storage-s3]
```

## Settings

| setting | kind | default |
|---|---|---|
| `endpoint` | str |  |
| `bucket` | str |  |
| `access_key` | str | *(secret)* |
| `secret_key` | str | *(secret)* |
| `secure` | bool | `True` |
| `region` | str |  |
| `prefix` | str |  |
| `create_bucket` | bool | `False` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
