# Modules: core, optional, plug and play

An application is made of packages: modules, an engine's subsystems, providers, a theme.
Its `module.yml` says which, and how they start by default; its administrator then
chooses, while it runs, which of the optional ones it uses.

## Core and optional

```yaml
modules:
  - {name: content, route: /, core: true}   # never disabled nor uninstalled
  - {name: auth, route: /cont, core: true}
  - {name: gallery, route: /galerii}         # managed: enabled by default
  - {name: forum, route: /sfat, enabled: false}   # managed: off until chosen
  - {name: maps, route: /harta, optional: true}   # if its setup fails, the site starts without it
```

A core module, and everything a core module or the theme depends on, is **locked**.
The others are managed in the admin panel or with `nest modules`.

## What the administrator chooses

The choices are kept in the workspace, `data/modules.yml`, laid over `module.yml` when
the application is made: the manifest is the code's (a deploy brings it), the choices are
the site's (a backup keeps them).

```
nest modules APP                         # every module: core/enabled/disabled/available
nest modules APP disable gallery         # its data stays
nest modules APP enable gallery
nest modules APP enable forum --route /forum    # one the manifest does not list
nest modules APP uninstall comments --yes       # its data and settings go (after a backup)
```

A change is never patched into the running application. It is:

1. **planned** first: disabling a module that another enabled module needs is refused,
   naming it ("forum needs auth, which is disabled"), and so is touching a locked one;
2. **backed up**: the workspace, into `backups/`;
3. **made**: the application is made with the new composition, which runs the migrations
   of the modules it gained. If it cannot start that way, the old composition is put back
   and the tables made for the new modules are taken down;
4. for an uninstall, **forgotten**: the other modules forget what they kept about it
   (seo its pages' descriptions, comments the threads on its records, through the
   `module.removed` lookup), the db interface drops its tables (its migrations down to
   nothing, through its `forget:` hook), its settings go;
5. **reloaded**: under `nest serve`, its workers are made again one by one (and the
   engine process with them), so no request is lost. `nest run` is restarted by hand.

Settings work the same way. Most are read when used (`host.live`), so a change in the
admin panel applies at once; the few that decide which routes exist (`restart: true` in
the manifest) reload the application when changed.

## What a module must do to be plug and play

- **Use other packages only by their front door**: the names in their manifest's
  `provides.exports`, imported from the package itself (`from nest_auth import known_as`),
  never their internals (`nest_auth.sessions`).
- **Depend on what it imports** (`deps:`). An optional partner is asked with a lookup
  (`host.lookup`, `host.gather`, `nest.answered`), never imported: the content module asks
  `seo.site_url`, the seo module asks `media.base`.
- **Never read another module's state** (`module_state(request, "media")`) or the host's
  private `_nest`; `host.admin_root`, `host.app_title` are public.
- **Own its tables** (its prefix, its migrations with a working `downgrade()`), and keep
  references to other modules' records as subjects (`"gallery.collection:7"`), so a
  `module.removed` answer can find them.
- **Keep no module globals**: what it keeps is in `host.state`, so an application made
  again (a reload, a change) starts clean.
- **Read settings when they are used**: `host.state.update(per_page=host.live("per_page", int))`.

`nest validate --strict` checks the first three in the code, and Nest's tests run it over
every package: a package that reaches into another fails the build.

## Not yet

- A game's subsystems (Saga) are listed but not managed: some only discover at run time
  the subsystems they rely on. Their manifests are made truthful first.
- Packages are installed with the application (its `pyproject.toml`, its image), not from
  the admin panel: the panel enables what is installed, it never runs `pip`.
