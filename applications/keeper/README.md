# Nest keeper

**Version 0.3.0** (in `module.yml`; raise it there and here together) · port 8000 · part of Nest

Nest's own application: it watches your deployed sites (Nest sites through their agents, other services with a web check), restarts and upgrades them through the host helper (`deploy/site/nest-host`), and shows the applications Nest knows, their plans and packages.

```sh
uv run nest run applications/keeper        # from Nest's repository: http://127.0.0.1:8000/
uv run nest plan applications/keeper       # what it is made of
```

Running it on a server: `deploy/DEPLOY.md` (one person's keeper, on a domain of yours). Documentation: docs/operate/keeper.md.
