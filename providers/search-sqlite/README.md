<!-- nest:readme -->
# SQLite search

Full-text search with SQLite FTS5, diacritics folded, ranked by BM25.

**Version 0.1.1** · provider · works with Nest `>=0.2,<1` · licence MIT

| | |
|---|---|
| package | `nest-search-sqlite` |
| name in a manifest | `search-sqlite` |
| category | infrastructure |
| reference | https://nest-framework.org/docs/reference/providers/search-sqlite |

## Using it

Bound by an application to the interface it implements:

```yaml
bind:
  nest.search:
    providers: [search-sqlite]
```

## Settings

| setting | kind | default |
|---|---|---|
| `path` | str | `data/search.db` |
| `title_weight` | float | `10.0` |

What each does: the reference page, or the admin panel's Settings.
<!-- /nest:readme -->
