"""Tests for event bus."""

import pytest
import asyncio

from hyusk.core.events import EventBus
from hyusk.models import Event, EventType


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish():
    """Test subscribing to and publishing events."""
    bus = EventBus()
    received_events = []

    async def handler(event: Event) -> None:
        received_events.append(event)

    await bus.subscribe(EventType.TASK_CREATED, handler)

    event = Event(type=EventType.TASK_CREATED, data={"test": "data"})
    await bus.publish(event)

    # Give handlers time to execute
    await asyncio.sleep(0.1)

    assert len(received_events) == 1
    assert received_events[0].type == EventType.TASK_CREATED
    assert received_events[0].data["test"] == "data"


@pytest.mark.asyncio
async def test_event_bus_multiple_handlers():
    """Test multiple handlers for same event."""
    bus = EventBus()
    handler1_called = []
    handler2_called = []

    async def handler1(event: Event) -> None:
        handler1_called.append(event)

    async def handler2(event: Event) -> None:
        handler2_called.append(event)

    await bus.subscribe(EventType.TASK_STARTED, handler1)
    await bus.subscribe(EventType.TASK_STARTED, handler2)

    event = Event(type=EventType.TASK_STARTED)
    await bus.publish(event)

    await asyncio.sleep(0.1)

    assert len(handler1_called) == 1
    assert len(handler2_called) == 1


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    """Test unsubscribing from events."""
    bus = EventBus()
    received_events = []

    async def handler(event: Event) -> None:
        received_events.append(event)

    await bus.subscribe(EventType.TASK_COMPLETED, handler)
    await bus.unsubscribe(EventType.TASK_COMPLETED, handler)

    event = Event(type=EventType.TASK_COMPLETED)
    await bus.publish(event)

    await asyncio.sleep(0.1)

    assert len(received_events) == 0


@pytest.mark.asyncio
async def test_event_bus_emit():
    """Test convenience emit method."""
    bus = EventBus()
    received_events = []

    async def handler(event: Event) -> None:
        received_events.append(event)

    await bus.subscribe(EventType.AGENT_STARTED, handler)

    await bus.emit(
        EventType.AGENT_STARTED,
        data={"agent": "test"},
    )

    await asyncio.sleep(0.1)

    assert len(received_events) == 1
    assert received_events[0].type == EventType.AGENT_STARTED
    assert received_events[0].data["agent"] == "test"
