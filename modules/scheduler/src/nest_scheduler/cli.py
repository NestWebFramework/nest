"""``nest scheduler``: the jobs from the command line.

nest scheduler jobs APP          every job: when, next, last
nest scheduler run APP JOB       run one now, here, and print its result (the site may run)
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any


def _app(path: str) -> Any:
    from nest.host import create_app

    return create_app(path, environ={**os.environ})


def _jobs(args: argparse.Namespace) -> int:
    from nest_scheduler import store

    app = _app(args.app)
    nest = app.state.nest
    scheduler = nest.module_state["scheduler"]["scheduler"]
    states = store.states(nest.bindings.get("nest.db"))
    for key, job in sorted(scheduler.jobs.items()):
        st = states.get(key)
        nxt = st.next_at.strftime("%Y-%m-%d %H:%M") if st and st.next_at else "-"
        last = (
            (("ok " if st.last_ok else "FAILED ") + st.last_at.strftime("%Y-%m-%d %H:%M"))
            if st and st.last_at
            else "never"
        )
        print(f"{key:32} {scheduler.when(job):26} next {nxt:16} last {last}")
    for p in scheduler.problems:
        print(f"✗ {p}")
    return 1 if scheduler.problems else 0


def _run(args: argparse.Namespace) -> int:
    app = _app(args.app)
    scheduler = app.state.nest.module_state["scheduler"]["scheduler"]
    job = scheduler.jobs.get(args.job)
    if job is None:
        print(f"✗ no job '{args.job}' ({', '.join(sorted(scheduler.jobs)) or 'none'})")
        return 1
    try:
        result = asyncio.run(scheduler.call(job, "asked"))
    except Exception as e:  # noqa: BLE001 - told, with its kind
        print(f"✗ {job.key}: {type(e).__name__}: {e}")
        return 1
    finally:
        scheduler.stop()
    print(f"✓ {job.key}: {result if result is not None else 'done'}")
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("scheduler", help="the jobs that run at set times")
    actions = p.add_subparsers(dest="scheduler_command", required=True)
    a = actions.add_parser("jobs", help="every job: when, next, last")
    a.add_argument("app")
    a.set_defaults(func=_jobs)
    a = actions.add_parser("run", help="run one job now, here")
    a.add_argument("app")
    a.add_argument("job")
    a.set_defaults(func=_run)
