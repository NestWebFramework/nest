# Themes: an application's look, chosen in its admin panel

A theme is a package (`type: theme`) with the layout every page is drawn in, its widgets
and its stylesheet. An application names one in its manifest (`application.theme`); its
administrator may choose another of the installed themes in the admin panel (**Themes**),
or with `nest themes`:

```
nest themes APP              # the installed themes; ● the one in use
nest themes APP use paper    # tried, kept in the workspace, the site reloaded
nest themes APP use          # back to module.yml's theme
```

Nest comes with three:

| Theme | Look |
|---|---|
| `base` | Plain and readable, system fonts, light and dark by the browser's preference. |
| `paper` | Editorial: a masthead with the name set large and the menu in small capitals between rules, a serif to read by, warm paper (ink at night). |
| `slate` | Modern, dark-first: a translucent header that stays on top, rounded cards with depth, pill buttons, teal accents (light by day). |

More are installed like any package (`nest packages APP add <theme>`, or the keeper's
Packages page); they then appear in the Themes page.

## Choosing one

The choice is kept in the workspace (`data/modules.yml`, `theme:`), so a deploy never
undoes it and a backup keeps it. A switch is **tried first**: the application is made with
the theme and its pages are rendered (the home page, a missing page, the admin panel's
frame); a theme that cannot show them is refused, so a broken theme can never take the
site, or the admin panel needed to switch back, down with it. Then the site reloads
(`nest serve`'s workers one by one, or in place under `nest run`). Each switch is in the
panel's change log. If a chosen theme is later removed, the site falls back to its
manifest's theme rather than not starting.

**Preview**: an administrator may see the site in a theme before choosing it. A signed
cookie (an hour at most) shows *them* the site in that theme, with a bar to go back or
stop; everyone else sees the theme in use, and the admin panel keeps the theme in use.

## Writing a theme

A theme can be built on another (`extends:`): its templates are looked for first, the
other's fill in what it lacks, and its stylesheet loads after the other's, restyling it.
`slate` is only a stylesheet on `base`; `paper` adds its own `layout.html`.

```yaml
module: {name: paper, id: nest.theme.paper, type: theme, version: 0.1.0, title: Paper}
main: nest_theme_paper
extends: base
deps: {base: ">=0.2,<1", htmx: ">=0.1,<1"}
styles: [paper.css]
preview: {bg: "#fbf8f1", surface: "#fffdf8", text: "#1f1b16", muted: "#6b6358", accent: "#9c2a1a", border: "#e4dccb"}
```

`preview:` gives the colours its card shows in the Themes page.

**The theme contract** (`nest validate --strict` checks it): a theme provides, itself or
through the theme it extends,

- `layout.html` with the blocks every page fills: `title`, `head`, `header`, `nav`,
  `language`, `content`, `footer` (and `lang`);
- `error.html` and `widgets/language.html`;

and, to be at home with every module, it keeps base's tokens (`--bg`, `--surface`,
`--text`, `--muted`, `--border`, `--accent`, `--accent-text`, `--focus`, `--ok`,
`--danger`, `--radius`, `--max`, `--font`) and shared classes (`card`, `stack`, `row`,
`field`, `notice`, `badge`, `tile`, `grid`, `container`, buttons and `.secondary`). Its
layout includes `admin/preview_bar.html` and `notifications/region.html` with
`ignore missing`, as base's does.

An application's own templates and stylesheet stay on top of any theme: one that
overrides `layout.html` keeps its frame and gets the theme's
tokens and shapes under its own skin.

## A theme for any application: settings

What is one site's own (its tagline, its banner, its footer's links, the categories its
home page shows) is a theme **setting**, not text in a template, so the same theme serves
any application. A theme declares its settings as a module does:

```yaml
settings:
  tagline: {label: Tagline, default: ""}
  banner:  {label: Banner picture, description: "A stored picture (uploads/...)", default: ""}
```

an application sets them in its manifest, and its administrator in **Settings** (each
theme in use has its section there):

```yaml
application:
  theme: morlaca-valley
  theme_settings:
    morlaca-valley: {tagline: "the village below the hill", banner: uploads/panorama.jpg}
```

Templates read them with `{{ theme_setting("tagline") }}`: the setting of the theme in use,
else of the theme it is built on, the first that is set, so themes built on one share its
settings and may say any of them otherwise. Texts are written in the site's words for
the translator (`{{ _(theme_setting("tagline")) }}`): the application's language packs
translate them like all its wording.

A theme links to a module without knowing the application: `{{ module_url("gallery") }}`
is where the application mounts it, or nothing when it has none (the link is left out).
A theme that uses a module's template helpers (content's `menu()`, `latest()`) lists it
under `uses:` and checks `is defined`, so an application without that module still has
its frame.

A layout may extend a frame its themes share (`{% extends "morlaca/frame.html" %}`); the
theme contract follows `extends` through the theme chain.

Nest comes with three more written this way: `morlaca-valley` (the
valley's colours, a cross-stitch band, a village's page as the home page), and built on
it `morlaca-heritage` (the name over a banner, a sidebar) and `morlaca-chronicle` (an
almanac's masthead, drop capitals). Each site gives them its own words through their
settings.
