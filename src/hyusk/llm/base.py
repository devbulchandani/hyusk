"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from hyusk.models import Message, ToolCall


class LLMResponse:
    """Response from an LLM provider."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        stop_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        raw_response: Any = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.stop_reason = stop_reason
        self.usage = usage or {}
        self.raw_response = raw_response

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0

    @property
    def has_content(self) -> bool:
        """Check if response contains text content."""
        return self.content is not None and len(self.content) > 0


class StreamChunk:
    """A chunk from a streaming LLM response."""

    def __init__(
        self,
        content: str | None = None,
        tool_call: ToolCall | None = None,
        stop_reason: str | None = None,
        is_final: bool = False,
    ):
        self.content = content
        self.tool_call = tool_call
        self.stop_reason = stop_reason
        self.is_final = is_final


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 120,
    ):
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider."""
        pass

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion.

        Args:
            messages: Conversation messages
            tools: Available tools in provider-specific format
            system: System prompt
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with content and/or tool calls
        """
        pass

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion.

        Args:
            messages: Conversation messages
            tools: Available tools in provider-specific format
            system: System prompt
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk instances
        """
        pass

    @abstractmethod
    def format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools into provider-specific format.

        Args:
            tools: Tools in standard format

        Returns:
            Tools in provider-specific format
        """
        pass

    @abstractmethod
    def parse_tool_calls(self, response: Any) -> list[ToolCall]:
        """Parse tool calls from provider response.

        Args:
            response: Raw provider response

        Returns:
            List of ToolCall objects
        """
        pass

    def supports_vision(self) -> bool:
        """Check if provider/model supports vision."""
        return False

    def supports_streaming(self) -> bool:
        """Check if provider supports streaming."""
        return True

    def get_context_window(self) -> int:
        """Get model context window size."""
        return 128000  # Default, override in subclasses
