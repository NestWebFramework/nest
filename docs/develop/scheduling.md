---
title: "Scheduled jobs"
description: "Jobs that run at set times or intervals: declared in a package's manifest, run once across all workers by the scheduler module, remembered across restarts, shown in the admin panel."
---

# Scheduled jobs

The **scheduler** module runs the jobs an application's packages declare at set times or
intervals: send due notifications every 30 seconds, forget old records every night, check other
sites every 5 minutes. It runs each job **once**, however many workers or containers serve
the application. It remembers when each job runs next, so a restart neither repeats nor
loses one, and the admin panel shows every job's runs.

It is for **real clock time**. A game's own time (its seasons and timers) keeps its own
clock and is not scheduled here.

## Declaring a job

A package declares its jobs in its `module.yml`, under `schedule:`:

```yaml
schedule:
  - name: cleanup
    run: nest_keys.jobs:cleanup    # package.module:function
    every: 24h                     # 30s, 15m, 6h, 1d
    catch_up: once
    description: Remove the accounts unused too long, telling the modules holding their data.
```

The job is named after its package: this one is `keys.cleanup`. The function takes the
job's context and returns a short text or a dict, which is kept as its result:

```python
def cleanup(ctx):
    from nest_keys import service

    st = ctx.host.settings
    unprotected, inactive = service.cleanup(
        ctx.host.bound("nest.db"),
        lambda user_id: ctx.host.gather("account.forget", user_id),
        unprotected_days=int(st.get("unprotected_days") or 14),
        inactive_days=int(st.get("inactive_days") or 365),
    )
    return f"removed {unprotected} unprotected and {inactive} inactive accounts"
```

`ctx.host` is the job's own package's host: its settings, bindings and workspace, as in
its `setup`. `ctx.why` says why the job runs (`due`, `catch-up`, `asked`), and `ctx.log`
is a logger named after the job.

| Key | Meaning |
|---|---|
| `name` | lowercase letters, digits, `-` and `_` |
| `run` | the function, as `package.module:function` |
| `every` | an interval: `30s`, `15m`, `6h`, `1d` (5 seconds at least) |
| `cron` | or a cron expression: `"30 3 * * *"`, `"*/15 * * * *"`, `"0 9 * * 1-5"`, `@daily` |
| `every_setting` | or one of the package's own settings, in seconds, read each time |
| `at_start` | also run it soon after the application starts (default no) |
| `catch_up` | missed while the application was down: `once` (run it when back, the default) or `skip` (wait for its next time) |
| `timeout` | an async job is cancelled after it (`30m`). A thread cannot be stopped; it is only marked |
| `thread` | `true` (the default): a blocking function, run in the job threads. An `async def` runs on the event loop either way |
| `enabled` | `false` lists it but never runs it |
| `description` | shown in the admin panel |

Give exactly one of `every`, `cron` and `every_setting`. Cron expressions have five
fields (minute, hour, day, month, weekday 0-6 from Sunday) and are read in the scheduler's
`timezone` (`Europe/Bucharest` by default).

## Changing a job in an application

An application changes a package's job in its own manifest, by the job's full name:

```yaml
schedule:
  - {job: push.send, every: 1m}
  - {job: keeper.prune, cron: "0 5 * * 0"}
  - {job: keys.cleanup, enabled: false}
```

It can change the timing, `enabled`, `at_start`, `catch_up` and `timeout`, but never the
function. Only the application can change another package's job.

## Once, however many workers

One process runs the jobs: the one that holds the **lease**, a row in the application's
database renewed every few seconds. Any worker of any container sharing that database
may take it when its holder stops renewing (`lease_seconds`, 60 by default), so the jobs
go on when a worker or a container goes. The same job never runs twice at once.

Blocking jobs run in the scheduler's own threads (`threads`, 4 by default), never in those
that answer the pages, so a long import does not slow the site.

> [!NOTE]
> Threads let blocking work (a download, a database import) wait without holding up
> anything else. They do not make Python compute faster in parallel. Heavy computing
> belongs in other processes fed by a queue, which is a separate tool from the scheduler.

## In the admin panel

**Admin → Scheduler** lists every job: when it runs, when next, how its last run went and
how long it took, and its failures in a row. **Run now** runs it within seconds;
**Pause** keeps it from running until **Resume**. A job's page lists its runs, with why
each ran and its result. Runs are kept `history_days` (30).

From the command line:

```sh
nest scheduler jobs APP          # every job: when, next, last
nest scheduler run APP JOB       # run one now, here, and print its result
```

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `timezone` | `Europe/Bucharest` | the zone cron expressions are read in |
| `threads` | 4 | threads for blocking jobs (1-32) |
| `history_days` | 30 | how long runs are kept |
| `lease_seconds` | 60 | how long the running process holds the jobs without renewing |
| `enabled` | true | off: no job runs in this application |

## A module that works with and without it

A module may keep a loop of its own for applications without the scheduler, and leave the
work to the scheduler when it is there:

```python
def setup(host):
    if host.has_module("scheduler"):
        return  # the scheduler runs the jobs in module.yml

    @host.background(single=True)
    async def loop(): ...
```

The keeper (`keeper.watch`, `keeper.prune`, `keeper.fetch`) does this.
