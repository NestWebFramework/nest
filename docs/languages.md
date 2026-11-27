# Languages: one site, an address per language

An application lists its languages in `module.yml`; the admin panel's **Languages** page
(`/admin/languages`) changes them later. Its choice is kept in the workspace
(`data/modules.yml`, `languages: {site: [...], default: ...}`) and wins over the manifest.
Adding a language changes no table: it is one more value, not one more column.

```yaml
application:
  languages: [ro, en]
  default_language: ro
  language_urls: prefix   # or cookie (the default)
```

## `language_urls: prefix`

- The default language is at the root (`/galerii/`); every other under its code
  (`/en/galerii/`). `/ro/...` is sent to `/...` for good (301), `/en` to `/en/`.
- The prefix sets the request's language and is removed before routing, so no module's
  routes change.
- On an English page, links to the site (`href`, `action`, `src`, `hx-*`), the site's own
  absolute addresses (canonical) and redirects' `Location` get `/en` back.
- Files (`/assets/`, `/media/`), Nest's own addresses (`/_nest/`), `robots.txt`,
  `sitemap.xml`, `/healthz` and the admin panel have one address only; `/en/assets/...` is
  redirected to `/assets/...`.
- Every page lists itself in each language in its head (`<link rel="alternate" hreflang>`,
  plus `x-default`), using `seo.site_url` when the seo module answers, else the request's
  host. A page that writes its own alternates keeps them.
- The language switch (`/_nest/language?language=en&next=/x/`) sends to `/en/x/` and sets
  no cookie: the address says the language.

`cookie` mode is unchanged: one address, the language in a cookie.

## A record's text in every language: text tables

A module keeps what is the same in every language in its own table, and its text beside
it in a **text table**: one row per record per language, the default language included.
Adding a language adds rows, never columns.

```python
from nest_db import model_base, text_table
from sqlalchemy import String, Text

Base = model_base("content")

class Entry(Base):
    __tablename__ = "content_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    ...

EntryText = text_table(Base, Entry, title=String(300), slug=String(200),
                       excerpt=Text, body=Text, unique=("slug",))
```

`content_entry_text` then has `owner_id` + `locale` (its key), the fields, `status`
(`published` or `draft`, per language), `updated_at` (when its text last changed) and
`source_updated_at` (the default language's `updated_at` a translation was made from).
`unique` fields are unique within a language: two languages may share a slug.

Reading and writing, from `nest_db`, one indexed query each:

| | |
|---|---|
| `localize(s, EntryText, ids, locale, default)` | each record's text in `locale`; the default's where there is none (`.fallback` says so) |
| `by_slug(s, EntryText, locale, slug)` | the record at an address in that language |
| `text_rows(s, EntryText, ids, locales)` | every row, `{id: {locale: row}}` |
| `save_text(s, EntryText, id, locale, values)` | writes; `updated_at` moves only on a real change |
| `text_state(row, source)` | `missing`, `draft`, `outdated` or `published` |

`ModuleHost.languages` and `ModuleHost.default_language` give the site's languages.

## The translations module

With `translations` in the application, editors get every language's text for every
module that declares its text tables:

```yaml
# the module's module.yml
uses: [translations]
translatable:
  entry:
    model: "nest_content.models:EntryText"
    label: Articles
    fields: {title: text, slug: slug, excerpt: textarea, body: html}
    edit: "{admin}/content/entries/{id}"
```

- **In the module's edit form:** `{{ translation_fields("content.entry", id) }}` writes
  each language but the default one (`tr_<language>_<field>`), with its state. Before
  saving, `nest.lookup("translations.check", {"subject", "id", "form"})` says what is
  wrong; after the module saved its default text, `nest.lookup("translations.save", ...)`
  writes the others. An all-empty language removes that translation.
- **Outdated:** when the default text changes, its translations are flagged until saved
  again, or ticked "Still matches the original".
- **Admin → Translations:** per kind and language, what is missing, outdated, a draft or
  published, and an editor beside the original ("Start from the Romanian text").
- **Export and import:** a JSON file of what is left (each text beside its original), for
  a translator; `nest translations export APP FILE --lang en`, `import`, `status`. A text
  whose original changed while it was away comes back outdated.
- `nest.lookup("translations.states", {"subject", "ids"})` for a module's own lists.

The module has no tables: the text stays in each module's own, and goes with it when the
module is uninstalled. `nest validate --strict` refuses a module that declares another
package's table. Without the module, a module reads its default rows and works in one
language.

## Content in every language

Content's entries, categories and tags, and menu labels keep their text in text tables
(`content_entry_text`, `content_term_text`, `content_menu_item_text`). The default
language's text stays in the records' own columns, which its pages read without a join,
and is mirrored in the text tables as the translations' source; records older than the
text tables get their default rows at start (one statement per table).

- **Translated addresses.** An English slug makes the English address, from the English
  slugs of the entry, its category and its parent pages (a link not yet translated takes
  the Romanian slug): `/stiai-ca/biserica/` in Romanian, `/en/did-you-know/the-church/`
  in English. Two English texts never share an address (`-2`). When a Romanian slug
  moves, the English addresses made from it follow.
- **Each address sends on to the language's own.** The Romanian address asked in English
  goes to the English one (301), the English one asked in Romanian to the Romanian one,
  so the language switch lands on the same page.
- **Not yet translated: the Romanian text.** `/en/stiai-ca/moara/` shows the Romanian
  text (its article marked `lang="ro"`), its links staying in English. It lists no English
  `hreflang` and keeps the Romanian page as its canonical, so search engines index the
  original only. A translation saved as a draft is not shown.
- **Lists, menus, search, feeds, sitemaps.** Listings and menus show each entry in the
  page's language (the Romanian where there is none). Each language has its own search
  index (`content.entry.en`). `/en/feed/` lists the translated entries. The sitemap (the
  seo module's, or content's own) lists each translated page at its English address.
- **Editors.** The entry and category forms have the English fields under the Romanian
  ones; the entries list shows where each stands (EN published, outdated, draft, missing);
  Admin → Translations has the backlog, the editor beside the original, export and import.

## Search words, galleries and maps

- **SEO.** What editors tell search engines about a page (its search title, description
  and keywords) has a row per language (`seo_meta_text`); the English ones are written in
  Admin → Translations ("Search titles and descriptions"). A translated page without them
  uses its own translated title and text, never the Romanian words, and leaves out the
  site-wide description and keywords (written in Romanian). The picture, noindex and a
  canonical override are the page's; the override applies to the Romanian page only, a
  translated page being its own canonical. `og:locale` says the page's language, and the
  sitemap lists each translated page at its address.
- **Galleries.** A gallery's title and description and each photo's caption and
  description have rows per language. A photo whose only words are a file name or a
  camera's record has none: there is nothing to translate. A gallery keeps its address
  in every language (`/galerii/iarna/`, `/en/galerii/iarna/`); one not yet translated
  shows the Romanian and tells search engines so.
- **Maps.** A map's and each marker's title and description have rows per language; the
  map asks for its markers in the page's language (`/en/harta/sat.geojson`), with links to
  the site's pages at their English addresses, and other modules' places (an article's
  pin) come in that language too (`map.points` is asked with `{"locale": "en"}`). Saving a
  map keeps each marker where it was, so its translations stay, outdated if its words
  changed.

Not translated yet: content's custom fields (an event's place), revisions of a
translation, and the site-wide settings (the SEO site description, the site's title).
Changing the default language of a site that has content is not supported yet.
