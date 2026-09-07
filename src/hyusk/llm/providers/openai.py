"""OpenAI GPT provider."""

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from hyusk.llm.base import LLMProvider, LLMResponse, StreamChunk
from hyusk.llm.messages import messages_to_openai_format
from hyusk.logging import get_logger
from hyusk.models import Message, ToolCall

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI GPT LLM provider.

    Also supports OpenAI-compatible APIs like OpenRouter, local models, etc.
    """

    def __init__(
        self,
        model: str = "gpt-4",
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 120,
        base_url: str | None = None,
    ):
        super().__init__(model, api_key, max_tokens, temperature, timeout)

        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        self.base_url = base_url

        client_kwargs = {
            "api_key": self.api_key,
            "timeout": float(timeout),
        }

        if base_url:
            client_kwargs["base_url"] = base_url
            logger.info(f"Using custom OpenAI base URL: {base_url}")

        self.client = AsyncOpenAI(**client_kwargs)

    @property
    def provider_name(self) -> str:
        return "openai"

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using GPT."""
        # Convert messages to OpenAI format
        formatted_messages = messages_to_openai_format(messages)

        # Add system message if provided
        if system:
            formatted_messages.insert(0, {"role": "system", "content": system})

        # Prepare request
        request_params: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }

        if tools:
            request_params["tools"] = self.format_tools(tools)
            request_params["tool_choice"] = "auto"

        logger.info(
            "Sending completion request to OpenAI",
            model=self.model,
            message_count=len(formatted_messages),
            has_tools=bool(tools),
        )

        try:
            response = await self.client.chat.completions.create(**request_params)

            # Parse response
            choice = response.choices[0]
            content = choice.message.content
            tool_calls = self.parse_tool_calls(response)

            usage = {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }

            logger.info(
                "Received completion from OpenAI",
                finish_reason=choice.finish_reason,
                has_content=bool(content),
                tool_calls_count=len(tool_calls),
                usage=usage,
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=choice.finish_reason,
                usage=usage,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {e}", error_type=type(e).__name__)
            raise

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming completion using GPT."""
        formatted_messages = messages_to_openai_format(messages)

        if system:
            formatted_messages.insert(0, {"role": "system", "content": system})

        request_params: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        if tools:
            request_params["tools"] = self.format_tools(tools)
            request_params["tool_choice"] = "auto"

        logger.info("Starting streaming completion from OpenAI", model=self.model)

        try:
            stream = await self.client.chat.completions.create(**request_params)

            tool_call_buffer: dict[int, dict[str, Any]] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # Text content
                if delta.content:
                    yield StreamChunk(content=delta.content)

                # Tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index

                        if idx not in tool_call_buffer:
                            tool_call_buffer[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }

                        if tc.function:
                            if tc.function.name:
                                tool_call_buffer[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_call_buffer[idx]["arguments"] += tc.function.arguments

                # Finish reason
                if chunk.choices[0].finish_reason:
                    # Yield accumulated tool calls
                    for tc_data in tool_call_buffer.values():
                        if tc_data["name"]:
                            try:
                                arguments = json.loads(tc_data["arguments"])
                            except json.JSONDecodeError:
                                arguments = {}

                            tool_call = ToolCall(
                                tool_name=tc_data["name"],
                                arguments=arguments,
                                metadata={"tool_call_id": tc_data["id"]},
                            )
                            yield StreamChunk(tool_call=tool_call)

                    yield StreamChunk(
                        stop_reason=chunk.choices[0].finish_reason,
                        is_final=True,
                    )

        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}", error_type=type(e).__name__)
            raise

    def format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools for OpenAI."""
        formatted = []

        for tool in tools:
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
            )

        return formatted

    def parse_tool_calls(self, response: Any) -> list[ToolCall]:
        """Parse tool calls from OpenAI response."""
        tool_calls = []

        choice = response.choices[0]
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                tool_call = ToolCall(
                    tool_name=tc.function.name,
                    arguments=arguments,
                    metadata={"tool_call_id": tc.id},
                )
                tool_calls.append(tool_call)

        return tool_calls

    def supports_vision(self) -> bool:
        """Check if model supports vision."""
        return "vision" in self.model.lower() or "gpt-4" in self.model.lower()

    def get_context_window(self) -> int:
        """Get context window for GPT models."""
        if "gpt-4-turbo" in self.model or "gpt-4-vision" in self.model:
            return 128000
        elif "gpt-4" in self.model:
            return 8192
        elif "gpt-3.5-turbo" in self.model:
            return 16385
        return 4096
