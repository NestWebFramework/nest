# Modules: core, optional, plug and play

An application is made of packages: modules, providers, a theme.
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

In the admin panel, **Modules** (`<admin>/modules`, administrators only) shows every
module: the core ones locked, the enabled, the disabled, and those installed but not
used, each with what it needs and what needs it. A module is disabled, enabled again,
added at an address, or uninstalled (its name typed to confirm) from there; the page
shows each step of the change and the latest changes (who, what, when, done or
refused, kept in `data/modules.log`). The command line does the same:

The choices are kept in the workspace, `data/modules.yml`, laid over `module.yml` when
the application is made: the manifest is the code's (a deploy brings it), the choices are
the site's (a backup keeps them).

```
nest modules APP                         # every module: core/enabled/disabled/available
nest modules APP disable gallery         # its data stays
nest modules APP enable gallery
nest modules APP enable forum --route /forum    # one the manifest does not list
nest modules APP uninstall comments --yes       # its data and settings go (after a backup)
nest modules APP versions                # each package's version: running, chosen, the registry's
nest modules APP version forum=0.3.0 content=0.2.1   # another version (up or down), one change
nest modules APP version forum=image     # back to the image's version
nest modules APP migrations forum        # its revisions: applied, current, its code's
nest modules APP migrate forum forum_0003   # up or down to a revision (head, base), after a backup
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
5. **reloaded**: under `nest serve`, its workers are made again one by one, so no
   request is lost; under `nest run`, a change made in
   the panel makes the application again in place. A change made with the command line
   reloads `nest serve`; `nest run` is then restarted by hand.

## Versions and migrations

A site may run another version of a package than the one it was built with: an update
from the registry, an older version, a module added from the registry. The admin panel
does it (Modules: **Update**, **Update all**, a module's **Use this version**, the
Registry tab's **Add**), and so does `nest modules APP version`.

A container's code is read only and made again at every restart, so the versions chosen
are kept in the workspace, which lasts: `packages/pins.json` says what was chosen, and
each version is unpacked from its wheel into `packages/<dist>-<version>/`, loaded ahead of
the image's packages when the application is made. Each choice remembers the image's
version at the time. A site deployed later with another image, whose packages may all be
other versions, decides again at every start:

| The image now has… | The choice |
|---|---|
| the version it was chosen over | used |
| a newer version, or the same one | set aside: the image wins (its tables migrate up at start) |
| an older version | kept: its tables may be migrated past what the image's knows |

and a choice used must still fit: what it requires must be there (the image's packages,
the other choices), and what the image's packages require of it must hold. One that does
not is set aside, and the panel says why. So a redeploy is never undone by an older
choice, nor broken by one that no longer fits.

A change runs in a process of its own, never in the running site:

1. each version is found in the registry (it must work with this nest-core and not be
   withdrawn), its wheel downloaded and checked: its sha256 as the registry lists it, and
   its signature when the package is pinned to keys (`nest trust`);
2. what each needs must be there after the change: a Nest package at a version its range
   takes (asked in the same change, chosen before, or the image's); anything else must be
   in the image already. A site never installs what is not Nest's (rebuild the image for
   that). Only pure-Python wheels are taken;
3. the workspace is **backed up**;
4. a module going to an **older** version has its **migrations taken down first**, with the
   code it runs now, to the newest revision the older version knows;
5. the choices are written and the application is made with them in a new process, which
   **migrates up** what moved up and proves the site starts (as production starts:
   migrations must be applied);
6. if it does not start, the choices before are put back and the application made again
   (its migrations up again where they were taken down); the backup stays for the worst
   case (`nest restore`, the site stopped);
7. the running site is **reloaded**: `nest serve`'s master takes the old code out before
   it forks the workers again, one by one; `nest run` makes the application again.

A module's migrations can also be moved by hand, up or down to any revision (the panel's
**Up to here** / **Down to here**, or `nest modules APP migrate`), after a backup. Below
the revision its code expects, the module may not work until it is migrated up again.

Every change, done or refused, is written in `data/modules.log` (the panel's History).

Settings work the same way. Most are read when used (`host.live`), so a change in the
admin panel applies at once; the few that decide which routes exist (`restart: true` in
the manifest) reload the application when changed.

## What a module must do to be plug and play

- **Use other packages only by their front door**: the names in their manifest's
  `provides.exports`, imported from the package itself (`from nest_auth import known_as`),
  never their internals (`nest_auth.sessions`).
- **Depend on what it imports** (`deps:`). An optional partner is named in `uses:` and
  asked with a lookup (`host.lookup`, `host.gather`, `nest.answered`), or imported only
  where it is used, never at load: the content module asks `seo.site_url`, the seo module
  asks `media.base`. What it `uses` is never pulled in; when the application has it, it
  is set up first.
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

## Installing packages

An application's admin panel enables what is installed; it never installs. Installing is
the server administrator's, from the **registry**: the packages this server trusts.

- Nest's own: every package in the Nest checkout it runs from (`$NEST_HOME`, else found
  from nest-core): its modules, providers, interfaces, themes.
- Others, in a registry file (`$NEST_REGISTRY`, else `~/.config/nest/registry.yml`), each
  pinned so what was vetted is what comes: a git source at a commit (40 hex digits, never
  a branch), or a package index at an exact version, over https.

```yaml
packages:
  - {name: shop, dist: nest-shop, version: "1.2.0", type: module, title: Shop,
     git: "https://example.org/nest-shop.git", rev: "3f2c…(40 hex)"}
```

```
nest packages APP                 # the registry: in use, installed, with another, available
nest packages APP add forum       # into pyproject.toml and module.yml's deps, then uv sync
nest packages APP remove forum    # refused while the application uses it
```

The keeper app does the same from its pages (an application, then **Packages**). To
install is to add the package to the application's contract: the dependency and where it
comes from in `pyproject.toml`, its version range under its ecosystem in `module.yml`,
then `uv sync`; if any step fails, both files are put back. It is not added to the
application's modules: it arrives *installed, not used*, and appears in the admin panel's
Modules page, ready to add, without restarting the site (a running process reads the new
package's path when it next looks). A package the application uses is uninstalled there
before it can be removed; one that came with others goes with them.

In a container the environment is the image's: install in development, commit, build.
