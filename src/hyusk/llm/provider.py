"""LLM provider interface.

Defines a stateless chat provider. V2 adds `chat_stream()` so callers can
render text deltas as the model produces them. `chat()` remains the
canonical contract and `chat_stream()` defaults to yielding one final
chunk for any provider that does not override it.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCallRequest:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tool(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class LLMChunk:
    """A single chunk of a streaming response.

    - text_delta: incremental text produced by the model.
    - tool_call_delta: a (partial or complete) tool call. Providers stream
      argument JSON; consumers should accumulate.
    - done: signals the end of the stream. The final `response` is also
      available for non-streaming callers.
    """

    text_delta: str = ""
    tool_call_delta: ToolCallRequest | None = None
    done: bool = False
    response: LLMResponse | None = None


class LLMProvider(abc.ABC):
    """Stateless chat provider.

    The agent maintains the conversation; the provider turns a list of
    messages into a response (or a stream of chunks).
    """

    name: str

    @abc.abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[LLMChunk]:
        """Default streaming implementation: call chat() and yield one chunk.

        Providers that support real streaming should override this.
        """
        response = self.chat(messages, tools, model=model, temperature=temperature)
        chunk = LLMChunk(done=True, response=response)
        if response.text:
            yield LLMChunk(text_delta=response.text)
        yield chunk

    # Convenience async wrapper for transports that want to consume the
    # stream from a coroutine (e.g. the daemon's WebSocket handler).
    async def aiter_chunks(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMChunk]:

        async def _gen() -> AsyncIterator[LLMChunk]:
            for c in self.chat_stream(messages, tools, model=model, temperature=temperature):
                yield c

        return _gen()
