---
title: "Install Nest"
description: "Install Nest with Python 3.12+ and uv, run the demonstration application, and find your way around the nest command."
---

# Install Nest

Nest is a Git repository with many Python packages in one uv workspace. You clone
it, let uv install everything, and run applications with the `nest` command.

## Requirements

| What | Version | Why |
|---|---|---|
| Python | 3.12 or newer | Nest's packages require `>=3.12`. The repository pins 3.13 in `.python-version`. |
| [uv](https://docs.astral.sh/uv/) | a recent release | It installs Python if needed, every workspace package, and runs the `nest` command. |
| Git | any | To clone the repository. |
| Linux or macOS | | Development happens on Linux (WSL2 works). |

You do not need a database server: by default an application keeps its data in
SQLite files in its own folder. PostgreSQL and MariaDB are available as providers
when you need them.

> [!NOTE]
> uv reads `.python-version` and downloads Python 3.13 if your system does not have
> it, so you do not have to install Python yourself.

## Clone and install

```sh
git clone https://github.com/NestWebFramework/nest.git
cd nest
uv sync
```

`uv sync` creates `.venv/` in the repository and installs the core, every module,
interface, provider and theme as editable packages. After it, every
command in this documentation is run from the repository root with `uv run`.

To check that everything is there:

```sh
uv run nest catalog            # every package Nest can see, with its type and version
uv run nest validate .         # every manifest against the contract for its type
```

## Run the demonstration application

`applications/hello` is the smallest application that uses every part of Nest: a
local module mounted at `/`, the `base` theme, an interface bound to a provider, an
htmx form answered by a fragment, and a live SSE connection.

```sh
uv run nest plan applications/hello     # what it is made of, in start order
uv run nest run applications/hello      # http://127.0.0.1:8100
```

Open [http://127.0.0.1:8100](http://127.0.0.1:8100). `nest run` serves the application on the port its
manifest gives (`application.port`, here 8100). Stop it with Ctrl+C.

While you develop, let it reload when files change:

```sh
uv run nest run applications/hello --reload
```

`nest run` also takes `--host`, `--port` and `--log-level`. Every application
answers a health check at `/_nest/health`, which lists its modules and whether each
one is ready.

### Where its data goes

On the first run Nest creates the application's **workspace**, by default
`~/.local/share/nest/hello/`. It holds the SQLite database, the search index, stored
files, runtime settings and, in development, a generated signing key. Set
`NEST_APP_WORKSPACE` to keep it somewhere else:

```sh
NEST_APP_WORKSPACE=/tmp/hello uv run nest run applications/hello
```

Deleting the workspace resets the application to empty. Your code never lives there.

## The nest command

Everything is done with one command. `uv run nest --help` lists the groups, and
`uv run nest <command> --help` explains one.

### Running and inspecting

| Command | What it does |
|---|---|
| `nest plan APP` | Shows what the application is made of, in start order, with routes and bindings |
| `nest run APP` | Serves it for development (`--reload` while you work) |
| `nest serve APP` | Runs it in production: gunicorn's master and workers (see [Deploying](../deploy.md)) |
| `nest check APP` | Checks what running it in production needs |
| `nest catalog` | Lists the packages Nest can see |
| `nest validate PATH` | Checks manifests against their contracts (`--strict` also checks the code keeps to them) |

### Building a site

| Command | What it does |
|---|---|
| `nest new app NAME` | Scaffolds an application (see [Your first application](first-application.md)) |
| `nest new module NAME` | Scaffolds a module |
| `nest modules APP` | Lists, enables, disables or uninstalls an application's modules |
| `nest themes APP` | Lists the installed themes, or switches to one |
| `nest packages APP` | Installs trusted packages into an application, or removes them |
| `nest auth create-user APP EMAIL` | Creates an account (`--role admin` for an administrator) |

### Data and operations

| Command | What it does |
|---|---|
| `nest db status APP` | Shows each module's migrations; `upgrade`, `downgrade`, `revision` change them |
| `nest backup APP` | Puts the workspace (databases, files, settings) in one archive |
| `nest restore APP ARCHIVE` | Puts a backup back into the workspace, with the application stopped |

### Module commands

Some modules add their own group of commands, for imports and maintenance:
`nest content`, `nest gallery`, `nest maps`, `nest comments`, `nest forum`,
`nest redirects`, `nest translations`, `nest keeper`, `nest agent`, `nest scheduler`,
`nest docs`. For example:

```sh
uv run nest content --help
uv run nest forum add-board applications/hello "General" --description "Anything about Nest."
```

### Publishing packages

`nest publish`, `nest login`, `nest keygen`, `nest trust`, `nest visibility`,
`nest yank` and `nest unyank` work with a Nest registry. See
[the registry](../registry.md).

## Running the tests

```sh
uv run pytest
```

The tests cover the core and every package in the repository. A module that reaches
into another module's internals fails them.

## Next

- [Write your first application](first-application.md).
- Read [the concepts](concepts.md) behind the words used here.
