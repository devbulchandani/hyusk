"""ToolRegistry: central catalog of tools available to the agent."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from ..core.errors import ToolNotFound
from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFound(f"no such tool: {name}") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def extend(self, tools: Iterable[Tool]) -> None:
        for t in tools:
            self.register(t)
