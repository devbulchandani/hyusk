"""LLM provider interface.

V1 defines a single interface and ships a default OpenAI-compatible HTTP
implementation. Additional providers (Anthropic native, etc.) can be added
later without changing the agent.
"""

from __future__ import annotations

import abc
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


class LLMProvider(abc.ABC):
    """Stateless chat provider.

    The agent maintains the conversation; the provider turns a list of
    messages into a response. Streaming can be added later without breaking
    this interface.
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
