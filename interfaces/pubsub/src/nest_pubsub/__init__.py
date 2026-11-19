"""The ``nest.pubsub`` interface."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class PubSub(Protocol):
    async def publish(self, channel: str, message: str) -> None:
        """Send ``message`` to every process listening on ``channel``, this one included."""
        ...

    def messages(self, channel: str) -> AsyncIterator[str]:
        """The messages on ``channel`` from now on, as they come (an async generator).
        It raises when the connection is lost; the caller listens again."""
        ...
