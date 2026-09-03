"""Lightweight typed event system.

The CLI subscribes to these events and renders them. Future clients
(WebSocket, mobile, voice) can subscribe to the same stream without
touching the core agent.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

try:
    from enum import StrEnum  # py3.11+
except ImportError:  # pragma: no cover
    from enum import Enum as StrEnum  # type: ignore[assignment]
from typing import Any


class EventType(StrEnum):
    AGENT_STARTED = "agent.started"
    AGENT_THINKING = "agent.thinking"
    AGENT_TEXT = "agent.text"
    AGENT_TOOL_CALL = "agent.tool_call"
    TOOL_STARTED = "tool.started"
    TOOL_OUTPUT = "tool.output"
    TOOL_COMPLETED = "tool.completed"
    AGENT_COMPLETED = "agent.completed"
    AGENT_ERROR = "agent.error"
    PROCESS_STARTED = "process.started"
    PROCESS_EXITED = "process.exited"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


Subscriber = Callable[[Event], None]


class EventBus:
    """In-process pub/sub for typed events."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass

        return unsubscribe

    def publish(self, event: Event) -> None:
        for sub in list(self._subscribers):
            try:
                sub(event)
            except Exception:
                # Never let one bad subscriber break the pipeline.
                pass

    def clear(self) -> None:
        self._subscribers.clear()


def drain(bus: EventBus, types: Iterable[EventType]) -> list[Event]:
    """Return a list-copy of currently buffered events of given types (no buffer here, just helper)."""
    return []
