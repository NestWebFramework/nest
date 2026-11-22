"""What several workers of one application must agree on (nest serve's phase 2): the
sign-in limit counted where every worker sees it, a shared cache on Redis, and a
background task that runs in one worker only."""

import asyncio
import shutil
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import test_auth
from nest_auth.models import Failure
from nest_auth.throttle import CacheThrottle, DbThrottle
from nest_cache_memory import MemoryCache
from sqlalchemy import select
from test_auth import PASSWORD, client_for, post, register

from nest import host as nest_host
from nest.manifest import load_manifest
from nest.serve import plan

site = test_auth.site  # the same small application, as a fixture


@pytest.fixture(autouse=True)
def no_fail_delay(monkeypatch):
    import nest_auth.web

    monkeypatch.setattr(nest_auth.web, "FAIL_DELAY", 0.0)


def wrong(c, email="ana@example.ro"):
    return post(c, "/auth/login", email=email, password="wrong password!")


def throttle_of(c):
    return c.app.state.nest.module_state["auth"]["throttle"]


def test_failures_in_one_worker_count_in_the_others(site, tmp_path):
    ws = tmp_path / "ws"
    with client_for(site, ws) as c:
        register(c)
    # two workers of one application: two applications on one workspace and database
    with client_for(site, ws) as one, client_for(site, ws) as two:
        assert isinstance(throttle_of(one), DbThrottle)
        for _ in range(2):
            assert wrong(one).status_code == 401
        assert wrong(two).status_code == 401
        for c in (one, two):  # three in all (an account's): both refuse, even the right password
            r = post(c, "/auth/login", email="ana@example.ro", password=PASSWORD)
            assert r.status_code == 429
        db = one.app.state.nest.bindings.get("nest.db")
        with db.session() as s:
            keys = s.scalars(select(Failure.key)).all()
        # each failure counted three ways (email and address, account, address), all hashed
        assert len(keys) == 9 and all(len(k) == 64 and "@" not in k for k in keys)


def test_a_cache_in_each_process_is_not_trusted_with_the_limit(site, tmp_path):
    manifest = site / "module.yml"
    manifest.write_text(
        manifest.read_text().replace(
            "nest.db: {providers: [db-sqlite]}",
            "nest.db: {providers: [db-sqlite]}\n  nest.cache: {providers: [cache-memory]}",
        )
    )
    with client_for(site, tmp_path / "ws") as c:
        assert isinstance(throttle_of(c), DbThrottle)  # cache-memory is per worker


def test_serve_warns_of_a_provider_that_keeps_its_values_per_worker(tmp_path):
    (tmp_path / "module.yml").write_text(
        "module: {name: demo, id: t.app.demo, type: application, version: 0.1.0}\n"
        "application: {title: Demo, port: 8123, theme: base}\n"
    )
    m = load_manifest(tmp_path)
    p = plan(tmp_path, m, {}, {"workers": "3"}, process_local=["cache-memory"])
    assert "cache-memory: each worker keeps its own values" in p.notes[0]
    assert not plan(tmp_path, m, {}, {"workers": "1"}, process_local=["cache-memory"]).notes


def test_the_memory_cache_counts_over_a_window():
    async def go():
        cache = MemoryCache()
        assert await cache.incr("k", 1, 60) == 1
        assert await cache.incr("k", 2, 60) == 3
        expires = cache._data["k"][1]
        await cache.incr("k", 1, 999)  # the window is not stretched
        assert cache._data["k"][1] == expires

    asyncio.run(go())


# --- Redis ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_url():
    server = shutil.which("redis-server") or shutil.which("valkey-server")
    if not server:
        pytest.skip("no redis-server here")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [server, "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
    )
    for _ in range(50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait(10)


def test_the_redis_cache_and_its_channels(redis_url):
    from nest_redis import create  # noqa: PLC0415

    async def go():
        settings = SimpleNamespace(url=redis_url, prefix="", timeout=2.0, max_connections=4)
        cache = create(settings, SimpleNamespace(app="demo"))
        try:
            assert await cache.ping()
            await cache.set("a", "1")
            assert await cache.get("a") == "1"
            assert await cache._r.get("demo:a") == b"1"  # the application's prefix
            await cache.delete("a")
            assert await cache.get("a") is None
            assert await cache.incr("n", 1, 60) == 1
            assert await cache.incr("n", 4, 60) == 5
            assert 0 < await cache._r.ttl("demo:n") <= 60
            await cache._r.expire("demo:n", 30)
            await cache.incr("n", 1, 60)  # an increment does not stretch the window
            assert await cache._r.ttl("demo:n") <= 30
            await cache.set("t", "x", ttl=1)
            await asyncio.sleep(1.2)
            assert await cache.get("t") is None
            assert await cache.incr("plain") == 1 and await cache._r.ttl("demo:plain") == -1
            heard = cache.messages("news")
            listening = asyncio.ensure_future(heard.__anext__())
            await asyncio.sleep(0.3)  # subscribed
            await cache.publish("news", "hello")
            assert await asyncio.wait_for(listening, 3) == "hello"
            assert await cache._r.pubsub_numsub("demo:news") == [(b"demo:news", 1)]
            await heard.aclose()
        finally:
            await cache._r.flushdb()
            await cache.aclose()

    asyncio.run(go())


def test_with_redis_bound_the_workers_count_in_the_cache(site, tmp_path, redis_url):
    manifest = site / "module.yml"
    manifest.write_text(
        manifest.read_text().replace(
            "nest.db: {providers: [db-sqlite]}",
            "nest.db: {providers: [db-sqlite]}\n  nest.cache: {providers: [redis]}",
        )
    )
    ws, env = tmp_path / "ws", {"NEST_SITE__REDIS__URL": redis_url}
    with client_for(site, ws, **env) as c:
        register(c)
    with client_for(site, ws, **env) as one, client_for(site, ws, **env) as two:
        assert isinstance(throttle_of(one), CacheThrottle)
        for c in (one, two, one):
            assert wrong(c).status_code == 401
        assert (
            post(two, "/auth/login", email="ana@example.ro", password=PASSWORD).status_code == 429
        )
        db = one.app.state.nest.bindings.get("nest.db")
        with db.session() as s:
            assert s.scalars(select(Failure)).all() == []  # counted in Redis, not the database
        # the right password, from another address: refused for neither
        assert wrong(one, "maria@example.ro").status_code == 401


def test_with_redis_bound_live_updates_cross_workers(site, tmp_path, redis_url):
    from nest.realtime import format_event  # noqa: PLC0415

    manifest = site / "module.yml"
    manifest.write_text(
        manifest.read_text().replace(
            "nest.db: {providers: [db-sqlite]}",
            "nest.db: {providers: [db-sqlite]}\n  nest.pubsub: {providers: [redis]}",
        )
    )
    ws, env = tmp_path / "ws", {"NEST_SITE__REDIS__URL": redis_url}
    with client_for(site, ws, **env) as one, client_for(site, ws, **env) as two:
        brokers = [c.app.state.nest.broker for c in (one, two)]
        assert all(b.relay is not None for b in brokers)
        for b in brokers:
            b.register("news", "test", public=True)

        async def follow():  # a visitor of worker two, in worker two's loop
            gen = brokers[1].stream(type("R", (), {"is_disconnected": _never})(), ["news"])
            await gen.__anext__()
            await asyncio.sleep(0.5)  # worker one publishes meanwhile (below)
            try:
                return await asyncio.wait_for(gen.__anext__(), 5)
            finally:
                await gen.aclose()

        import threading  # noqa: PLC0415

        result = {}
        t = threading.Thread(
            target=lambda: result.update(got=two.portal.call(follow))  # type: ignore[union-attr]
        )
        t.start()
        time.sleep(0.3)
        one.portal.call(_publish, brokers[0])  # type: ignore[union-attr]
        t.join(10)
        assert result["got"] == format_event("e", "from worker one")


async def _never():
    return False


async def _publish(broker):
    broker.publish("news", "e", "from worker one")


# --- one worker runs it ------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="flock is POSIX")
def test_a_single_background_task_runs_in_one_worker_and_moves_on(tmp_path, monkeypatch):
    monkeypatch.setattr(nest_host, "SINGLE_RETRY_S", 0.05)
    ran: list[str] = []

    def task_for(worker):
        async def tick():
            ran.append(worker)
            await asyncio.sleep(3600)

        return nest_host._single(tick, tmp_path / "run" / "x.lock", "demo.tick")

    async def go():
        a = asyncio.create_task(task_for("a")())
        await asyncio.sleep(0.1)
        b = asyncio.create_task(task_for("b")())
        await asyncio.sleep(0.3)
        assert ran == ["a"]  # b waits for the lock
        a.cancel()  # the worker running it stops
        await asyncio.gather(a, return_exceptions=True)
        await asyncio.sleep(0.3)
        assert ran == ["a", "b"]  # and another takes over
        b.cancel()
        await asyncio.gather(b, return_exceptions=True)

    asyncio.run(go())
