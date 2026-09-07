"""Event bus for Hyusk."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from hyusk.logging import get_logger
from hyusk.models import Event, EventType

logger = get_logger(__name__)

# Type alias for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Central event bus for distributing events across Hyusk components."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to an event type with a handler.

        Args:
            event_type: Type of event to subscribe to
            handler: Async function to call when event occurs
        """
        async with self._lock:
            self._handlers[event_type].append(handler)
            logger.debug(
                f"Subscribed to {event_type.value}",
                handler=handler.__name__,
                total_handlers=len(self._handlers[event_type]),
            )

    async def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type.

        Args:
            event_type: Type of event to unsubscribe from
            handler: Handler to remove
        """
        async with self._lock:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
                logger.debug(
                    f"Unsubscribed from {event_type.value}",
                    handler=handler.__name__,
                    remaining_handlers=len(self._handlers[event_type]),
                )

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribed handlers.

        Args:
            event: Event to publish
        """
        async with self._lock:
            handlers = self._handlers[event.type].copy()

        if not handlers:
            logger.debug(f"No handlers for event {event.type.value}", event_id=str(event.id))
            return

        logger.info(
            f"Publishing event {event.type.value}",
            event_id=str(event.id),
            task_id=str(event.task_id) if event.task_id else None,
            agent_id=str(event.agent_id) if event.agent_id else None,
            handlers_count=len(handlers),
        )

        # Execute all handlers concurrently
        tasks = []
        for handler in handlers:
            task = asyncio.create_task(self._execute_handler(handler, event))
            tasks.append(task)

        # Wait for all handlers to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_handler(self, handler: EventHandler, event: Event) -> None:
        """Execute a single event handler with error handling.

        Args:
            handler: Handler function to execute
            event: Event to pass to handler
        """
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Error in event handler {handler.__name__}",
                event_type=event.type.value,
                event_id=str(event.id),
                error=str(e),
            )
            logger.exception("Handler exception details")

    async def emit(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> Event:
        """Convenience method to create and publish an event.

        Args:
            event_type: Type of event
            data: Event data
            task_id: Optional task ID
            agent_id: Optional agent ID

        Returns:
            Created event
        """
        event = Event(
            type=event_type,
            data=data or {},
            task_id=task_id,
            agent_id=agent_id,
        )

        await self.publish(event)
        return event

    def get_handler_count(self, event_type: EventType) -> int:
        """Get number of handlers subscribed to an event type.

        Args:
            event_type: Event type to check

        Returns:
            Number of subscribed handlers
        """
        return len(self._handlers[event_type])

    async def clear_handlers(self, event_type: EventType | None = None) -> None:
        """Clear handlers for an event type or all handlers.

        Args:
            event_type: Specific event type to clear, or None to clear all
        """
        async with self._lock:
            if event_type:
                self._handlers[event_type].clear()
                logger.info(f"Cleared handlers for {event_type.value}")
            else:
                self._handlers.clear()
                logger.info("Cleared all event handlers")


# Global event bus instance
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(event_bus: EventBus) -> None:
    """Set the global event bus instance."""
    global _event_bus
    _event_bus = event_bus
