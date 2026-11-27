---
title: "Nest: web sites and applications from modules"
description: Nest builds web sites and applications from modules (content, galleries, maps, comments, a forum) with themes, languages, an admin panel and a package registry.
hero:
  title: Build sites from modules
  lead: Nest is a Python framework for web sites and applications made of reusable modules. Write a short manifest, choose your modules, theme and languages; Nest plans it, checks it and runs it.
  actions:
    - {label: Get started, href: /docs/start/install}
    - {label: Read the documentation, href: /docs/}
  code: |
    uv run nest new app my-site
    cd my-site && uv run nest run .
features:
  - {title: Modules, text: "Content, galleries, maps, comments, a forum, messages, notifications: each reusable, each with its settings, admin pages and migrations.", href: /docs/modules}
  - {title: Themes, text: "Every module's pages fit every theme. Themes have settings, so one theme serves many sites.", href: /docs/themes}
  - {title: Languages, text: "An address per language, translated content with fallbacks, translations managed in the admin panel.", href: /docs/languages}
  - {title: Running it, text: "One container per site, its data on the host, upgrades that back up, migrate and roll back by themselves.", href: /docs/deploy-ispconfig}
---

## Why Nest

Nest keeps what a site is (its modules, settings, theme, languages) in one place you
can read, and everything generic in modules every site shares. A magazine and a
photo archive run on the same framework, with the same admin panel, the same
deployment and the same upgrades.
