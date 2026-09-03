"""Event bus tests."""

from __future__ import annotations

from hyusk.events.events import Event, EventBus, EventType


def test_subscribe_and_publish():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    bus.publish(Event(type=EventType.AGENT_STARTED, data={"x": 1}))
    assert len(seen) == 1
    assert seen[0].data["x"] == 1


def test_unsubscribe():
    bus = EventBus()
    seen = []
    unsub = bus.subscribe(lambda e: seen.append(e))
    bus.publish(Event(type=EventType.AGENT_STARTED))
    unsub()
    bus.publish(Event(type=EventType.AGENT_STARTED))
    assert len(seen) == 1


def test_subscriber_error_does_not_break_pipeline():
    bus = EventBus()
    good_seen = []

    def bad(event):
        raise RuntimeError("boom")

    bus.subscribe(bad)
    bus.subscribe(lambda e: good_seen.append(e))
    bus.publish(Event(type=EventType.AGENT_STARTED))
    assert len(good_seen) == 1
