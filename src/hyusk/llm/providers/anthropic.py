"""Anthropic Claude provider."""

from collections.abc import AsyncIterator
from typing import Any

import anthropic

from hyusk.llm.base import LLMProvider, LLMResponse, StreamChunk
from hyusk.llm.messages import messages_to_anthropic_format
from hyusk.logging import get_logger
from hyusk.models import Message, MessageRole, ToolCall

logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider.

    Also supports custom base URLs for Anthropic-compatible APIs.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4",
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 120,
        base_url: str | None = None,
    ):
        super().__init__(model, api_key, max_tokens, temperature, timeout)

        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self.base_url = base_url

        client_kwargs = {
            "api_key": self.api_key,
            "timeout": float(timeout),
        }

        if base_url:
            client_kwargs["base_url"] = base_url
            logger.info(f"Using custom Anthropic base URL: {base_url}")

        self.client = anthropic.AsyncAnthropic(**client_kwargs)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using Claude."""
        # Extract system messages
        system_content = system or self._extract_system_messages(messages)

        # Convert messages to Anthropic format
        formatted_messages = messages_to_anthropic_format(messages)

        # Prepare request
        request_params: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }

        if system_content:
            request_params["system"] = system_content

        if tools:
            request_params["tools"] = self.format_tools(tools)

        logger.info(
            "Sending completion request to Anthropic",
            model=self.model,
            message_count=len(formatted_messages),
            has_tools=bool(tools),
        )

        try:
            response = await self.client.messages.create(**request_params)

            # Parse response
            content = self._extract_content(response)
            tool_calls = self.parse_tool_calls(response)

            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

            logger.info(
                "Received completion from Anthropic",
                stop_reason=response.stop_reason,
                has_content=bool(content),
                tool_calls_count=len(tool_calls),
                usage=usage,
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=response.stop_reason,
                usage=usage,
                raw_response=response,
            )

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}", error_type=type(e).__name__)
            raise

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using Claude."""
        system_content = system or self._extract_system_messages(messages)
        formatted_messages = messages_to_anthropic_format(messages)

        request_params: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        if system_content:
            request_params["system"] = system_content

        if tools:
            request_params["tools"] = self.format_tools(tools)

        logger.info("Starting streaming completion from Anthropic", model=self.model)

        try:
            async with self.client.messages.stream(**request_params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield StreamChunk(content=event.delta.text)
                        elif hasattr(event.delta, "partial_json"):
                            # Tool call in progress
                            pass

                    elif event.type == "message_delta":
                        if event.delta.stop_reason:
                            yield StreamChunk(
                                stop_reason=event.delta.stop_reason,
                                is_final=True,
                            )

                # Get final message to extract tool calls
                final_message = await stream.get_final_message()
                tool_calls = self.parse_tool_calls(final_message)

                if tool_calls:
                    for tool_call in tool_calls:
                        yield StreamChunk(tool_call=tool_call)

        except anthropic.APIError as e:
            logger.error(f"Anthropic streaming error: {e}", error_type=type(e).__name__)
            raise

    def format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools for Anthropic."""
        formatted = []

        for tool in tools:
            formatted.append(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
            )

        return formatted

    def parse_tool_calls(self, response: Any) -> list[ToolCall]:
        """Parse tool calls from Anthropic response."""
        tool_calls = []

        for block in response.content:
            if block.type == "tool_use":
                tool_call = ToolCall(
                    tool_name=block.name,
                    arguments=block.input,
                    metadata={"tool_use_id": block.id},
                )
                tool_calls.append(tool_call)

        return tool_calls

    def supports_vision(self) -> bool:
        """Claude supports vision."""
        return "claude" in self.model.lower()

    def get_context_window(self) -> int:
        """Get context window for Claude models."""
        if "claude-3" in self.model or "claude-sonnet-4" in self.model:
            return 200000
        return 100000

    def _extract_system_messages(self, messages: list[Message]) -> str:
        """Extract and combine system messages."""
        system_parts = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_parts.append(msg.text_content)

        return "\n\n".join(system_parts) if system_parts else ""

    def _extract_content(self, response: Any) -> str | None:
        """Extract text content from response."""
        text_parts = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        return "".join(text_parts) if text_parts else None
