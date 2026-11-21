# Nest packages

**Version 0.1.0** (in `module.yml`; raise it there and here together) · port 8600 · part of Nest

The Nest package registry: registry.nest-framework.org, where Nest's packages are published and installed from.

```sh
uv run nest run applications/registry        # from Nest's repository: http://127.0.0.1:8600/
uv run nest plan applications/registry       # what it is made of
```

Running it on a server: applications/registry/deploy (and docs/registry-deploy.md).
