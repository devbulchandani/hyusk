"""Agent loop tests using a fake LLM provider."""

from __future__ import annotations

import pytest

from hyusk.agent.loop import Agent
from hyusk.core.errors import AgentLoopLimit
from hyusk.events.events import EventBus, EventType
from hyusk.llm.provider import LLMResponse, Message, ToolCallRequest
from hyusk.permissions.policy import PermissionPolicy
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    def chat(self, messages, tools=None, *, model=None, temperature=None):
        self.calls.append(list(messages))
        if not self.responses:
            return LLMResponse(text="done")
        return self.responses.pop(0)


def _echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="echo",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission=READ,
        execute=lambda a: {"echoed": a["x"]},
    )


def test_agent_handles_single_tool_call():
    provider = FakeProvider(
        [
            LLMResponse(
                text="let me check",
                tool_calls=[ToolCallRequest(name="echo", arguments={"x": "hi"}, id="c1")],
            ),
            LLMResponse(text="done"),
        ]
    )
    reg = ToolRegistry()
    reg.register(_echo_tool())
    bus = EventBus()
    agent = Agent(
        llm=provider,
        registry=reg,
        policy=PermissionPolicy(),
        bus=bus,
        max_iterations=5,
    )
    result = agent.run([], user_input="hi")
    assert result.text == "done"
    # provider was called twice
    assert len(provider.calls) == 2
    # last call includes the tool result
    last = provider.calls[-1]
    tool_msgs = [m for m in last if m.role == "tool"]
    assert tool_msgs and tool_msgs[0].name == "echo"
    assert "echoed" in tool_msgs[0].content


def test_agent_emits_events():
    seen: list[EventType] = []
    bus = EventBus()
    bus.subscribe(lambda e: seen.append(e.type))
    provider = FakeProvider([LLMResponse(text="ok")])
    reg = ToolRegistry()
    agent = Agent(llm=provider, registry=reg, policy=PermissionPolicy(), bus=bus)
    agent.run([], user_input="x")
    assert EventType.AGENT_STARTED in seen
    assert EventType.AGENT_COMPLETED in seen


def test_agent_loop_limit():
    responses = [
        LLMResponse(
            text="",
            tool_calls=[ToolCallRequest(name="echo", arguments={"x": "y"}, id=str(i))],
        )
        for i in range(10)
    ]
    provider = FakeProvider(responses)
    reg = ToolRegistry()
    reg.register(_echo_tool())
    bus = EventBus()
    agent = Agent(
        llm=provider,
        registry=reg,
        policy=PermissionPolicy(),
        bus=bus,
        max_iterations=2,
    )
    with pytest.raises(AgentLoopLimit):
        agent.run([], user_input="loop")


def test_agent_end_to_end_with_fake_tool_and_events():
    """Full agent run, multiple iterations, events emitted, final answer produced."""
    tool_calls_log: list[str] = []

    def fake_list(args):
        tool_calls_log.append(args["path"])
        return {"entries": [{"name": "x.txt", "type": "file", "size": 1, "modified": 0}]}

    reg = ToolRegistry()
    reg.register(
        Tool(
            name="list_directory",
            description="list",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            permission=READ,
            execute=fake_list,
        )
    )

    provider = FakeProvider(
        [
            LLMResponse(
                text="checking",
                tool_calls=[
                    ToolCallRequest(name="list_directory", arguments={"path": "."}, id="c1"),
                ],
            ),
            LLMResponse(text="all done"),
        ]
    )
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e.type))

    agent = Agent(llm=provider, registry=reg, policy=PermissionPolicy(), bus=bus, max_iterations=5)
    result = agent.run([], user_input="what is here?")

    assert result.text == "all done"
    assert result.iterations == 2
    assert tool_calls_log == ["."]
    assert EventType.TOOL_STARTED in events
    assert EventType.TOOL_COMPLETED in events
    assert EventType.AGENT_COMPLETED in events
