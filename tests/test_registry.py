"""Tool registry tests."""

from __future__ import annotations

import pytest

from hyusk.core.errors import InvalidInput, ToolNotFound
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


def _make_tool(name: str, perm: str = READ) -> Tool:
    return Tool(
        name=name,
        description=f"desc {name}",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission=perm,
        execute=lambda a: {"echo": a.get("x")},
    )


def test_register_and_get():
    reg = ToolRegistry()
    t = _make_tool("foo")
    reg.register(t)
    assert reg.get("foo") is t
    assert reg.has("foo")


def test_duplicate_registration_fails():
    reg = ToolRegistry()
    reg.register(_make_tool("foo"))
    with pytest.raises(ValueError):
        reg.register(_make_tool("foo"))


def test_missing_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolNotFound):
        reg.get("nope")


def test_list_and_names():
    reg = ToolRegistry()
    reg.register(_make_tool("a"))
    reg.register(_make_tool("b"))
    assert sorted(reg.names()) == ["a", "b"]
    assert len(reg.all()) == 2


def test_validate_required_arg():
    reg = ToolRegistry()
    reg.register(_make_tool("foo"))
    with pytest.raises(InvalidInput):
        reg.get("foo").run({})  # missing 'x'
    out = reg.get("foo").run({"x": "hi"})
    assert out == {"echo": "hi"}
