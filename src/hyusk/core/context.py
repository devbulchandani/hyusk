"""Context manager for LLM requests."""

from typing import Any
from uuid import UUID

from hyusk.database import get_database
from hyusk.logging import get_logger
from hyusk.models import Message, MessageRole

logger = get_logger(__name__)


class ContextManager:
    """Manages context construction for LLM requests."""

    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages
        self.db = get_database()

    async def build_context(
        self,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build context for an LLM request.

        Args:
            conversation_id: Conversation to load messages from
            task_id: Task to associate context with
            system_prompt: System instructions
            tools: Available tools

        Returns:
            Context dictionary with messages, system, and tools
        """
        messages = []

        # Load conversation messages if provided
        if conversation_id:
            messages = await self.load_conversation_messages(conversation_id)

        # Truncate if needed
        if len(messages) > self.max_messages:
            logger.info(
                f"Truncating {len(messages)} messages to {self.max_messages}",
                conversation_id=str(conversation_id) if conversation_id else None,
            )
            messages = self._truncate_messages(messages)

        return {
            "messages": messages,
            "system": system_prompt,
            "tools": tools or [],
            "conversation_id": conversation_id,
            "task_id": task_id,
        }

    async def load_conversation_messages(self, conversation_id: UUID) -> list[Message]:
        """Load messages from a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of messages
        """
        # TODO: Load from database
        # For now, return empty list
        # This will be implemented when we have message persistence
        logger.debug(
            "Loading conversation messages",
            conversation_id=str(conversation_id),
        )
        return []

    async def save_message(
        self,
        message: Message,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> None:
        """Save a message to the database.

        Args:
            message: Message to save
            conversation_id: Associated conversation
            task_id: Associated task
        """
        if conversation_id:
            message.conversation_id = conversation_id
        if task_id:
            message.task_id = task_id

        # TODO: Implement database persistence
        logger.debug(
            "Message saved",
            message_id=str(message.id),
            role=message.role.value,
        )

    def _truncate_messages(self, messages: list[Message]) -> list[Message]:
        """Truncate messages to fit context window.

        Keeps system messages and most recent messages.

        Args:
            messages: All messages

        Returns:
            Truncated message list
        """
        # Separate system and non-system messages
        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        other_messages = [m for m in messages if m.role != MessageRole.SYSTEM]

        # Keep most recent messages
        available_slots = self.max_messages - len(system_messages)
        kept_messages = other_messages[-available_slots:]

        # Combine back
        return system_messages + kept_messages

    def create_system_prompt(
        self,
        base_prompt: str,
        additional_context: str | None = None,
    ) -> str:
        """Create a system prompt with optional additional context.

        Args:
            base_prompt: Base system instructions
            additional_context: Additional context to include

        Returns:
            Complete system prompt
        """
        parts = [base_prompt]

        if additional_context:
            parts.append(additional_context)

        return "\n\n".join(parts)


# Global context manager instance
_context_manager: ContextManager | None = None


def get_context_manager() -> ContextManager:
    """Get the global context manager instance."""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager


def set_context_manager(manager: ContextManager) -> None:
    """Set the global context manager instance."""
    global _context_manager
    _context_manager = manager
