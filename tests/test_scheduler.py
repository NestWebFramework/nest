"""The scheduler: cron times, the jobs the manifests declare and the application changes,
one process at a time through the lease, runs remembered, the admin panel."""

from __future__ import annotations

import asyncio
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nest_auth.sessions import create_user
from nest_scheduler import cron, store
from nest_scheduler import jobs as specs
from nest_scheduler.models import utcnow

from nest import create_app

# --- cron ------------------------------------------------------------------------------------

AT = datetime(2026, 11, 21, 10, 7)  # a Saturday


@pytest.mark.parametrize(
    ("text", "nxt"),
    [
        ("30 3 * * *", datetime(2026, 11, 22, 3, 30)),
        ("*/15 * * * *", datetime(2026, 11, 21, 10, 15)),
        ("0 9 * * 1-5", datetime(2026, 11, 23, 9, 0)),  # Monday
        ("0 0 1 * *", datetime(2026, 12, 1, 0, 0)),
        ("@weekly", datetime(2026, 11, 22, 0, 0)),  # Sunday
        ("0 12 13 * 5", datetime(2026, 11, 27, 12, 0)),  # the 13th or a Friday: Friday first
        ("0 0 29 2 *", datetime(2028, 2, 29, 0, 0)),
        ("0 0 * * 7", datetime(2026, 11, 22, 0, 0)),  # 7 is Sunday too
    ],
)
def test_cron_next_times(text, nxt):
    assert cron.parse(text).next_after(AT) == nxt


@pytest.mark.parametrize(
    "bad", ["* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *", "5-1 * * * *"]
)
def test_cron_refuses_what_it_cannot_read(bad):
    with pytest.raises(cron.CronError):
        cron.parse(bad)


def test_cron_never_coming_is_said():
    with pytest.raises(cron.CronError):
        cron.parse("0 0 31 2 *").next_after(AT)


# --- the jobs ----------------------------------------------------------------------------------


def test_jobs_are_collected_and_changed_by_the_application():
    sections = [
        ("trains", [{"name": "sync", "run": "nest_trains.jobs:sync", "every": "6h"}]),
        ("keeper", [{"name": "prune", "run": "nest_keeper.jobs:prune", "cron": "15 4 * * *"}]),
        (
            "gari",
            [{"job": "trains.sync", "every": "3h"}, {"job": "keeper.prune", "enabled": False}],
        ),
    ]
    found, problems = specs.collect(sections, "gari")
    assert problems == []
    assert found["trains.sync"].every == 3 * 3600 and found["trains.sync"].when == "every 3h"
    assert (
        found["keeper.prune"].enabled is False and found["keeper.prune"].cron.text == "15 4 * * *"
    )


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ({"name": "x", "run": "m:f"}, "exactly one"),
        ({"name": "x", "run": "m:f", "every": "6h", "cron": "@daily"}, "exactly one"),
        ({"name": "x", "run": "m:f", "every": "soon"}, "not a duration"),
        ({"name": "x", "run": "m:f", "every": "1s"}, "at least"),
        ({"name": "X Y", "run": "m:f", "every": "1h"}, "lowercase"),
        ({"name": "x", "run": "nowhere", "every": "1h"}, "package.module:function"),
        ({"name": "x", "run": "m:f", "every": "1h", "catch_up": "twice"}, "catch_up"),
    ],
)
def test_a_bad_job_is_a_problem_not_a_crash(raw, says):
    found, problems = specs.collect([("mod", [raw])], "app")
    assert found == {} and len(problems) == 1 and says in problems[0]


def test_only_the_application_changes_another_packages_job():
    sections = [
        ("a", [{"name": "x", "run": "m:f", "every": "1h"}]),
        ("b", [{"job": "a.x", "every": "1m"}]),
        ("app", [{"job": "a.nothing", "every": "1m"}]),
    ]
    found, problems = specs.collect(sections, "app")
    assert found["a.x"].every == 3600
    assert any("only the application" in p for p in problems)
    assert any("no package declares" in p for p in problems)


# --- in an application --------------------------------------------------------------------

TICK = {
    "module.yml": """
        module:
          name: tickapp
          id: test.app.tick
          type: application
          version: 0.1.0
        application: {title: Tick, port: 8000, theme: base}
        modules:
          - {name: tick}
          - {name: scheduler}
          - {name: admin, route: /admin}
          - {name: auth, route: /cont}
        bind:
          nest.db: {providers: [db-sqlite]}
        schedule:
          - {job: tick.slow, cron: "0 3 * * *"}
    """,
    "modules/tick/module.yml": """
        module: {name: tick, id: test.module.tick, type: module, version: 0.1.0}
        main: tick
        pages: false
        settings:
          seconds: {type: int, default: 120}
        schedule:
          - {name: count, run: "tick:count", every_setting: seconds}
          - {name: slow, run: "tick:slow", every: 1h, description: A blocking job.}
          - {name: fails, run: "tick:fails", every: 1d, at_start: true}
          - {name: later, run: "tick:count", every: 1h, catch_up: skip}
    """,
    "modules/tick/tick.py": """
        import asyncio, threading
        RUNS = []

        async def count(ctx):
            RUNS.append(("count", ctx.why, ctx.host.settings.get("seconds")))
            return {"counted": len(RUNS)}

        def slow(ctx):
            RUNS.append(("slow", threading.current_thread().name))
            return "slept"

        def fails(ctx):
            raise RuntimeError("the portal is down")

        def setup(host):
            pass
    """,
}


def tick_app(tmp_path: Path):
    root = tmp_path / "tickapp"
    for rel, body in TICK.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})


def test_it_runs_the_jobs_once_and_remembers(tmp_path):
    app = tick_app(tmp_path)
    with TestClient(app):
        nest = app.state.nest
        scheduler = nest.module_state["scheduler"]["scheduler"]
        db = nest.bindings.get("nest.db")
        assert scheduler.problems == []
        assert set(scheduler.jobs) == {"tick.count", "tick.slow", "tick.fails", "tick.later"}
        assert scheduler.jobs["tick.slow"].when == "0 3 * * *"  # the application's change
        assert scheduler.every(scheduler.jobs["tick.count"]) == 120  # its package's setting

        # one holder at a time
        assert store.hold_lease(db, scheduler.holder, 60)
        assert not store.hold_lease(db, "another:1:x", 60)
        scheduler.prepare(db)
        states = store.states(db)
        assert states["tick.fails"].next_at <= utcnow()  # at_start: now
        assert states["tick.count"].next_at > utcnow() + timedelta(seconds=100)

        async def round_():
            await scheduler.run_due(db)
            await asyncio.gather(*scheduler.running.values())

        asyncio.run(round_())
        fails = store.states(db)["tick.fails"]
        assert fails.last_ok is False and "the portal is down" in fails.last_result
        assert fails.failures == 1 and fails.next_at > utcnow() + timedelta(hours=23)

        # asked in the admin panel: it runs at once, in the job threads if it blocks
        store.ask(db, "tick.slow", run_now=True)
        store.ask(db, "tick.count", run_now=True)
        asyncio.run(round_())
        runs = scheduler.host.resolve("tick", "tick:RUNS")
        assert ("count", "asked", 120) in runs
        assert any(r[0] == "slow" and r[1].startswith("nest-job") for r in runs)
        slow = store.states(db)["tick.slow"]
        assert slow.last_ok and slow.last_result == "slept" and not slow.run_now
        assert [r.why for r in store.runs(db, "tick.slow")] == ["asked"]

        # paused: it waits, even when due
        store.ask(db, "tick.count", paused=True)
        store.set_next(db, "tick.count", utcnow() - timedelta(minutes=1))
        before = len(runs)
        asyncio.run(round_())
        assert len(runs) == before

        # missed while down: catch_up skip waits for its next time
        store.set_next(db, "tick.later", utcnow() - timedelta(hours=5))
        scheduler.prepare(db)
        assert store.states(db)["tick.later"].next_at > utcnow()
        store.let_go(db, scheduler.holder)
        assert store.hold_lease(db, "another:1:x", 60)  # let go: another takes it


def test_the_admin_panel_lists_runs_and_pauses(tmp_path):
    app = tick_app(tmp_path)
    with TestClient(app) as c:
        nest = app.state.nest
        db = nest.bindings.get("nest.db")
        nest.module_state["scheduler"]["scheduler"].prepare(db)
        create_user(db, "admin@example.org", "correct horse battery", roles=("admin",))
        c.get("/healthz")
        c.post(
            "/cont/login",
            data={
                "csrf_token": c.cookies["nest_csrf"],
                "email": "admin@example.org",
                "password": "correct horse battery",
            },
        )
        h = {"X-CSRF-Token": c.cookies["nest_csrf"]}
        page = c.get("/admin/scheduler/").text
        assert "tick.count" in page and "every 2m (seconds)" in page and "0 3 * * *" in page
        assert c.post("/admin/scheduler/job/tick.count/pause", headers=h).status_code == 200
        assert store.states(db)["tick.count"].paused
        c.post("/admin/scheduler/job/tick.count/run", headers=h)
        assert store.states(db)["tick.count"].run_now
        assert c.post("/admin/scheduler/job/tick.count/explode", headers=h).status_code == 404
        assert c.get("/admin/scheduler/job/nothing.here").status_code == 404
        assert "A blocking job." in c.get("/admin/scheduler/job/tick.slow").text


def test_the_packages_jobs_are_declared_well():
    from nest.catalog import Catalog

    sections = [
        (e.name, e.manifest.raw["schedule"])
        for e in Catalog.discover()
        if "schedule" in e.manifest.raw
    ]
    found, problems = specs.collect(sections, "none")
    assert problems == []
    assert {"push.send", "keeper.watch", "keeper.prune"} <= set(found)
