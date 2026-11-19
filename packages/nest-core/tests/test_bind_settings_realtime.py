import asyncio
from typing import Protocol

import pytest

from nest.bind import build_settings, conformance, env_name
from nest.manifest import SettingSpec
from nest.realtime import Broker, TopicError, format_event
from nest.settings import SettingsError, SettingsStore

SPECS = {
    "url": SettingSpec(type="str", required=True),
    "size": SettingSpec(type="int", default=10),
    "token": SettingSpec(type="str", secret=True),
}


def test_env_name():
    assert env_name("my-app", "cache-redis", "url") == "NEST_MY_APP__CACHE_REDIS__URL"


def test_settings_are_typed_and_env_overrides():
    settings, problems = build_settings(
        "app", "p", SPECS, {"url": "x", "size": "5"}, {"NEST_APP__P__SIZE": "7"}
    )
    assert problems == []
    assert settings.url == "x" and settings.size == 7 and settings.token is None


def test_a_secret_written_in_the_manifest_is_refused():
    _, problems = build_settings("app", "p", SPECS, {"url": "x", "token": "hunter2"}, {})
    assert problems == [
        "p.token is secret; set it in the environment as NEST_APP__P__TOKEN, never in module.yml"
    ]


def test_a_secret_from_the_environment_is_hidden():
    settings, _ = build_settings("app", "p", SPECS, {"url": "x"}, {"NEST_APP__P__TOKEN": "s3"})
    assert settings.token.get_secret_value() == "s3"
    assert "s3" not in repr(settings)


def test_missing_and_unknown_settings_are_reported():
    _, problems = build_settings("app", "p", SPECS, {"colour": "red"}, {})
    assert any("p has no setting 'colour'" in p for p in problems)
    _, problems = build_settings("app", "p", SPECS, {}, {})
    assert any(p.startswith("p.url: Field required (or set NEST_APP__P__URL)") for p in problems)


class Store(Protocol):
    async def get(self, key: str) -> str | None: ...
    def size(self) -> int: ...


def test_conformance_checks_presence_async_and_parameters():
    class Good:
        async def get(self, key):
            return None

        def size(self):
            return 0

    class Bad:
        def get(self, name):
            return None

    assert conformance(Store, Good(), "good") == []
    problems = conformance(Store, Bad(), "bad")
    assert "bad.get() must be async, as Store declares" in problems
    assert "bad.get(name) does not match Store.get(key)" in problems
    assert "bad does not provide Store.size()" in problems


def test_settings_store(tmp_path):
    store = SettingsStore(tmp_path / "s.conf", "app", {"NEST_APP__BLOG__LOCKED": "1"})
    store.declare(
        "blog",
        {
            "per_page": SettingSpec(type="int", default=20),
            "locked": SettingSpec(type="bool", default=False),
        },
    )
    assert store.get("blog.per_page") == 20
    store.set("blog.per_page", "50")
    assert SettingsStore(tmp_path / "s.conf", "app", {}).get  # file is readable again
    reread = SettingsStore(tmp_path / "s.conf", "app", {})
    reread.declare("blog", {"per_page": SettingSpec(type="int")})
    assert reread.get("blog.per_page") == 50
    assert store.get("blog.locked") is True
    with pytest.raises(SettingsError, match="set by the environment"):
        store.set("blog.locked", False)
    with pytest.raises(SettingsError, match="not a int"):
        store.set("blog.per_page", "many")
    with pytest.raises(SettingsError, match="not a declared setting"):
        store.get("blog.nope")
    assert oct((tmp_path / "s.conf").stat().st_mode & 0o777) == "0o600"


def test_sse_format():
    assert (
        format_event("card", "<p>a</p>\n<p>b</p>")
        == "event: card\ndata: <p>a</p>\ndata: <p>b</p>\n\n"
    )
    with pytest.raises(ValueError):
        format_event("a\nb", "x")


def test_topics_are_denied_unless_registered_on_purpose():
    broker = Broker()
    with pytest.raises(TopicError, match="public=True on purpose"):
        broker.register("t", "m")
    broker.register("t", "m", public=True)
    with pytest.raises(TopicError, match="already registered"):
        broker.register("t", "other", public=True)
    with pytest.raises(TopicError, match="not registered"):
        broker.publish("nope", "e", "d")


class FakeRequest:
    async def is_disconnected(self):
        return False


def test_stream_sends_snapshot_then_live_events_and_drops_slow_clients():
    async def scenario():
        broker = Broker()
        broker.register("t", "m", public=True, snapshot=lambda: ("e", "snap"))
        gen = broker.stream(FakeRequest(), ["t"])
        assert await gen.__anext__() == "retry: 3000\n\n"
        assert await gen.__anext__() == "event: e\ndata: snap\n\n"
        broker.publish("t", "e", "live")
        assert await gen.__anext__() == "event: e\ndata: live\n\n"
        for i in range(100):  # more than the queue holds
            broker.publish("t", "e", str(i))
        assert broker.subscribers("t") == 0
        await gen.aclose()

    asyncio.run(scenario())


def test_a_setting_changed_by_another_process_is_seen(tmp_path, monkeypatch):
    import nest.settings as st
    from nest.manifest import SettingSpec

    path = tmp_path / "settings.conf"
    one = st.SettingsStore(path, "app", {})
    two = st.SettingsStore(path, "app", {})  # another worker
    for s in (one, two):
        s.declare("maps", {"provider": SettingSpec(type="str", default="osm")})
    monkeypatch.setattr(st, "CHECK_EVERY", 0.0)
    one.set("maps.provider", "maptiler")
    import os

    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))  # a later write
    assert two.get("maps.provider") == "maptiler"


class FakeRelay:
    """nest.pubsub in one process: every listener hears every message, its own included."""

    def __init__(self):
        self.listeners: list[asyncio.Queue] = []

    async def publish(self, channel, message):
        for q in self.listeners:
            q.put_nowait(message)

    async def messages(self, channel):
        q: asyncio.Queue = asyncio.Queue()
        self.listeners.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.listeners.remove(q)


def test_brokers_relay_events_to_each_others_visitors_in_order():
    async def scenario():
        relay = FakeRelay()
        one, two = Broker(), Broker()  # two workers
        tasks = []
        for b in (one, two):
            b.register("t", "m", public=True)
            tasks += [asyncio.create_task(fn()) for fn in b.tasks(relay, "realtime:app")]
        await asyncio.sleep(0.01)
        here, there = one.stream(FakeRequest(), ["t"]), two.stream(FakeRequest(), ["t"])
        for gen in (here, there):
            assert await gen.__anext__() == "retry: 3000\n\n"
        for i in range(5):
            one.publish("t", "e", str(i))
        for gen in (here, there):  # once each, in order: none twice to the worker that made it
            assert [await gen.__anext__() for _ in range(5)] == [
                f"event: e\ndata: {i}\n\n" for i in range(5)
            ]
        one.publish("t", "tick", "x", local=True)  # this worker's only
        two.publish("t", "e", "back")
        assert await there.__anext__() == "event: e\ndata: back\n\n"
        assert await here.__anext__() == "event: tick\ndata: x\n\n"
        assert await here.__anext__() == "event: e\ndata: back\n\n"
        assert one.listening("nobody") and not Broker().listening("nobody")
        for gen in (here, there):
            await gen.aclose()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_a_handlers_thread_may_publish():
    async def scenario():
        broker = Broker()
        broker.register("t", "m", public=True)
        broker.tasks(None, "")
        gen = broker.stream(FakeRequest(), ["t"])
        await gen.__anext__()
        await asyncio.to_thread(broker.publish, "t", "e", "from a thread")
        assert await asyncio.wait_for(gen.__anext__(), 2) == "event: e\ndata: from a thread\n\n"
        await gen.aclose()

    asyncio.run(scenario())
