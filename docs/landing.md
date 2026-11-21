---
title: "Nest: web sites and applications from modules"
description: Nest builds web sites and applications from modules (content, galleries, dictionaries, timetables, maps, comments, games) with themes, languages, an admin panel and a package registry.
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
  - {title: Modules, text: "Content, galleries, maps, comments, a dictionary, a railway timetable, a forum, messages, a game engine: each reusable, each with its settings, admin pages and migrations.", href: /docs/modules}
  - {title: Themes, text: "Every module's pages fit every theme. Themes have settings, so one theme serves many sites.", href: /docs/themes}
  - {title: Languages, text: "An address per language, translated content with fallbacks, translations managed in the admin panel.", href: /docs/languages}
  - {title: Running it, text: "One container per site, its data on the host, upgrades that back up, migrate and roll back by themselves.", href: /docs/deploy-ispconfig}
showcase_title: Sites built with Nest
showcase:
  - {title: "Gări.ro", image: images/sites/gari-home.png, url: /docs/sites/gari, text: "The Romanian train timetable from data.gov.ro: journeys with changes, split-flap boards, live trains."}
  - {title: Regionalisme, image: images/sites/regionalisme-home.png, url: /docs/sites/regionalisme, text: "A dictionary of regional words: proposals, comments, hangman, English explanations."}
  - {title: Morlaca, image: images/sites/morlaca-home.png, url: /docs/sites/morlaca, text: "A village's site: history, galleries, maps, in Romanian and English."}
  - {title: Transilpedia, image: images/sites/transilpedia-home.png, url: /docs/sites/transilpedia, text: "The encyclopedia of Transylvania: thousands of articles, translated."}
---

## Why Nest

Nest keeps what a site is (its modules, settings, theme, languages) in one place you
can read, and everything generic in modules every site shares. A dictionary site and a
railway timetable run on the same framework, with the same admin panel, the same
deployment and the same upgrades.
