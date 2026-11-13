"""Realtime: named topics streamed to the browser as Server-Sent Events.

The rules are RoboHub's: one SSE connection per page, carrying every topic the
page follows; a snapshot first, so a reconnect sees the current state; named
events, so htmx's ``sse-swap`` routes each to its element. A topic is refused
unless a module registered it, either public or with an ``authorize`` check.
A client too slow to keep up is dropped; it reconnects and gets a snapshot.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

Event = tuple[str, str]
Snapshot = Callable[[], Event | Iterable[Event] | None | Awaitable[Any]]
Authorize = Callable[[Request], bool | Awaitable[bool]]

PING_SECONDS = 15.0
MAX_TOPICS_PER_CONNECTION = 16


class TopicError(Exception):
    pass


@dataclass
class Topic:
    name: str
    owner: str
    snapshot: Snapshot | None
    authorize: Authorize | None
    public: bool


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    dropped: bool = False


def format_event(event: str, data: str) -> str:
    if "\n" in event or "\r" in event:
        raise ValueError("an event name is one line")
    lines = data.splitlines() or [""]
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Broker:
    def __init__(self) -> None:
        self.topics: dict[str, Topic] = {}
        self._subscribers: dict[str, set[_Subscriber]] = defaultdict(set)

    def register(
        self,
        name: str,
        owner: str,
        *,
        snapshot: Snapshot | None = None,
        authorize: Authorize | None = None,
        public: bool = False,
    ) -> Topic:
        if name in self.topics:
            raise TopicError(f"topic '{name}' is already registered by {self.topics[name].owner}")
        if not public and authorize is None:
            raise TopicError(f"topic '{name}': pass authorize=..., or public=True on purpose")
        topic = Topic(name, owner, snapshot, authorize, public)
        self.topics[name] = topic
        return topic

    def subscribers(self, name: str) -> int:
        return len(self._subscribers.get(name, ()))

    def publish(self, topic: str, event: str, data: str) -> None:
        """Send ``event`` to everyone following ``topic``. Never blocks."""
        if topic not in self.topics:
            raise TopicError(f"topic '{topic}' is not registered")
        for sub in list(self._subscribers.get(topic, ())):
            try:
                sub.queue.put_nowait((event, data))
            except asyncio.QueueFull:
                sub.dropped = True
                self._subscribers[topic].discard(sub)

    async def allowed(self, request: Request, names: list[str]) -> tuple[int, str] | None:
        """None when every topic may be followed; otherwise (status, reason)."""
        if not names:
            return 400, "name at least one topic"
        if len(names) > MAX_TOPICS_PER_CONNECTION:
            return 400, f"at most {MAX_TOPICS_PER_CONNECTION} topics per connection"
        for name in names:
            topic = self.topics.get(name)
            if topic is None:
                return 404, f"no topic '{name}'"
            if not topic.public and not await _maybe(topic.authorize(request)):
                return 403, f"not allowed to follow '{name}'"
        return None

    async def stream(self, request: Request, names: list[str]) -> AsyncIterator[str]:
        sub = _Subscriber()
        for name in names:
            self._subscribers[name].add(sub)
        try:
            yield "retry: 3000\n\n"
            for name in names:
                snapshot = self.topics[name].snapshot
                if snapshot is None:
                    continue
                result = await _maybe(snapshot())
                if result is None:
                    continue
                events = [result] if isinstance(result, tuple) else list(result)
                for event, data in events:
                    yield format_event(event, data)
            while not sub.dropped:
                try:
                    event, data = await asyncio.wait_for(sub.queue.get(), PING_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield format_event(event, data)
        finally:
            for name in names:
                self._subscribers[name].discard(sub)
