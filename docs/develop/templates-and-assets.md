---
title: "Templates, assets and translations"
description: "Jinja templates and render(), htmx fragments, overriding a module's templates, the theme contract, template globals, static files and asset(), bundled styles, and JSON translation catalogs."
---

# Templates, assets and translations

An application has one Jinja environment for every page and fragment. Modules bring
their templates, the theme brings the frame (`layout.html`), and the application may
override any of them without forking a package.

## Where a template is found

The loader looks in this order, and the first match wins:

1. the application's `templates/` folder: its own overrides;
2. the theme's `templates/`, then the theme it extends;
3. each module's `templates/`, under the module's name.

A module's templates are therefore reached as `"<module>/<file>"`: the forum's
`templates/topic.html` is `"forum/topic.html"`. To change that page for one site, the
application ships its own `templates/forum/topic.html`; a theme may do the same for
every site that uses it.

Autoescaping is on, and undefined names are errors (`StrictUndefined`): a typo in a
template fails loudly instead of rendering empty. Test an optional value with
`is defined`, as the gallery does for the seo module's helpers:

```jinja
{% block title %}{{ seo_page_title("gallery.index", _("Galleries")) if seo_page_title is defined else _("Galleries") ~ " · " ~ app.title }}{% endblock %}
```

## render() and fragments

`render(request, template, **values)` returns an `HTMLResponse`. It takes only three
keyword arguments of its own: `fragment`, `status_code` and `headers`; every other keyword
reaches the template.

One handler answers both a full page load and an htmx request: name a `{% block %}` as
the fragment, and `render` returns only that block when htmx asked for it (an `HX-Request`
that is not a boosted navigation):

```python
from nest import is_htmx, render

if is_htmx(request):
    return render(
        request,
        "forum/topic.html",
        fragment="reply",
        topic=t,
        error=None,
        body="",
        base=state["base"],
    )
return RedirectResponse(f"{topic_url(state['base'], t)}?last=1#post-{p.id}", status_code=303)
```

```jinja
{% extends "layout.html" %}
{% block content %}
<h1>{{ topic.title }}</h1>
{# ... the posts ... #}
{% block reply %}
<form id="reply" class="stack" method="post" action="{{ base }}/t/{{ topic.id }}/reply"
      hx-post="{{ base }}/t/{{ topic.id }}/reply" hx-target="#reply" hx-swap="outerHTML">
  {{ csrf_field }}
  {% if error %}<p class="notice danger" role="alert">{{ error }}</p>{% endif %}
  <div class="field"><label for="reply-body">{{ _("Reply") }}</label><textarea id="reply-body" name="body" rows="5" required>{{ body }}</textarea></div>
  <button type="submit">{{ _("Send") }}</button>
</form>
{% endblock %}
{% endblock %}
```

Without JavaScript the form posts and the handler redirects (303) back to the topic; with
htmx the same handler returns the `reply` block and htmx swaps it in. A block may use what
the template sets up outside any block (its imports and `set`s).

`render` adds `Vary: HX-Request` to every response. A request with the `X-Nest-Embed`
header gets only the named block (`content` by default): how an application shows any
module's page inside its own screen.

For an event sent outside a request (server-sent events), `host.render_block(name, block,
**context)` renders a block to a string.

## The theme contract

Every theme provides, itself or through the theme it `extends`:

- `layout.html`, with the blocks `title`, `head`, `header`, `nav`, `language`, `content`
  and `footer`;
- `error.html`, the page for an error status;
- `widgets/language.html`, the language switch.

`layout.html` must also show `{{ nest_credit }}` in its footer, **outside** the `footer`
block, so a page that fills the block keeps it. The base theme's footer:

```jinja
<footer class="site-footer">
  <div class="container">{% block footer %}{{ app.title }}{% endblock %}{{ nest_credit }}</div>
</footer>
```

`check_theme` (in `nest/themes.py`) checks all this when an administrator switches themes
and in `nest validate --strict`; a switch is also tried by rendering the home page, a
missing page and the admin panel before it is kept. See [themes](../themes.md).

Module templates extend `layout.html` and fill `content` (and `title`, `head` when they
have something to say there), so they work in every theme.

## What every template can use

| Name | What it is |
|---|---|
| `_("text", **params)` | the text in the page's language; `{name}` placeholders are filled from `params` |
| `ngettext(singular, plural, n, **params)` | the plural form for `n`; `{n}` is filled |
| `locale`, `languages`, `admin_languages` | the page's language, the site's, the admin panel's |
| `app` | `{name, title}` of the application |
| `request` | the request |
| `csrf_field` | the hidden form field with the CSRF token: put it in every POST form |
| `csrf_token` | the token itself, for an `hx-headers` attribute |
| `is_htmx` | whether this request wants a fragment |
| `asset(module, path)` | the versioned address of a module's static file |
| `styles` | the stylesheet bundle's address (the theme's `head` links it) |
| `theme_setting(name, default="")` | a setting of the theme in use, or of a theme it extends |
| `module_url(name, path="")` | where the application mounts a module, or `None` without it |
| `shortcodes(text)` | `text` with every module's shortcodes expanded |
| `nest_credit` | the "Built with Nest" line, in the page's language |
| `in_admin`, `admin_frame`, `lang_prefix` | whether the page is in the admin panel; its frame; `/en` on a prefixed page |

Modules add their own with `host.context` (see [a module](a-module.md)); a module that
another may lack is tested with `is defined`. Filters are added with
`host.template_filter(name, fn)`.

`theme_setting` and `module_url` let a theme be written for any application:

```jinja
{% set tagline = theme_setting("tagline") %}
{% if module_url("content") %}{% include "content/_search.html" %}{% endif %}
```

## Static files and asset()

A module's `static/` folder is served at `/assets/<module>/`. Link a file with
`asset()`, never a hand-written path:

```jinja
{% block head %}<script src="{{ asset('geo', 'locate.js') }}" defer></script>{% endblock %}
```

`asset('geo', 'locate.js')` writes `/assets/geo/locate.js?v=<version>-<stamp>`: the
module's version and its static files' latest change. An address with `?v=` is served
with `Cache-Control: public, max-age=31536000, immutable`, so browsers keep it a year and
still get a changed file at once (its address changed). Without `?v=` a file is kept an
hour.

Scripts are files, never inline: the page policy allows `script-src 'self'` only (see
[security](security.md)). A script that needs data reads it from `data-` attributes.

## Styles: one bundle per page

A page loads one stylesheet. Nest puts it together when the application starts: the
theme's `styles`, then each module's `styles` in start order, then the application's own,
so the later restyles the earlier. The admin panel has its own bundle with the modules'
`admin_styles`.

```yaml
styles: [forum.css]  # its base look; an application restyles it
```

Bundles are served at `/assets/_bundle/site.css` and `/assets/_bundle/admin.css` with a
hash in the query, kept a year; while developing, a changed stylesheet rebuilds the
bundle. A relative `url()` in a stylesheet (a font, a picture) is rewritten to the
module's versioned asset address. Build a module's look on the theme's tokens (CSS custom
properties) so it follows any theme.

## htmx

The `htmx` module ships htmx and its configuration for a strict page policy (no eval, no
injected styles, requests to the same origin only). The base theme includes it in its
`<head>`:

```jinja
{% include "htmx/head.html" %}
```

and, for a signed-in user or in the admin panel, sends the CSRF token with every htmx
request:

```jinja
<body{% if (user is defined and user) or in_admin %} hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'{% endif %}>
```

For an anonymous visitor, forms carry `{{ csrf_field }}`, which htmx posts with the form.

`toast(request, text, level="success")` tells the person who made the request something
("Saved."), whatever the handler returns next; the notifications module shows it, and
without it the toast is dropped.

## Translations

A package lists its catalogs in `module.yml`; a catalog not listed is not loaded:

```yaml
locales:
  - {locale: ro, file: locales/ro.json}
  - {locale: en, file: locales/en.json}
```

A catalog is JSON that maps the English text to its translation. A plural is a list with
one form per plural category of the language (Romanian has three):

```json
{
  "Comments": "Comentarii",
  "Sign in to comment.": "Autentifică-te pentru a comenta.",
  "{n} comment": [
    "{n} comentariu",
    "{n} comentarii",
    "{n} de comentarii"
  ]
}
```

```jinja
{{ ngettext("{n} comment", "{n} comments", total) }}
```

Code writes English; text not in a catalog shows as written. In Python, outside a
template, `translator(request)` (from `nest`) gives the page's words, and
`host.translator(locale)` the site's words outside a request (a sitemap).

Catalogs merge in start order and the application's come last, so an application can
reword any module. To reword one module only, its catalog uses a scoped key:
`"forum::Board": "Secțiune"` applies in the forum's templates alone. See
[languages](../languages.md).

A package's own words (its title, its description, its admin page's) are never found by
their English text, which may change or be the same as another's: they are found by the
package's name in its `module.yml`. Its catalog says them with keys that start with `@`,
which belong to it alone:

```json
{
  "@title": "Forum",
  "@description": "Secțiuni, subiecte și mesaje, cu moderare…",
  "@admin.title": "Forum",
  "@admin.description": "Secțiunile, subiectele și mesajele lor."
}
```

`"@title"` in forum's catalog is kept as `forum@title`; an application's catalog may
reword it with that whole key. A template asks with `about(name, field, default)`:
`{{ about("forum", "title", "Forum") }}`, the default being the manifest's words. The
admin menu's groups are identifiers too, their labels `group@<id>`. Every Nest package
carries its Romanian words this way.
