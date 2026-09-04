"""Anthropic provider tests (no network)."""

from __future__ import annotations

from hyusk.llm.anthropic import AnthropicProvider, _convert_messages, _parse_response
from hyusk.llm.provider import LLMProvider, Message, ToolCallRequest


def test_subclass_of_llm_provider():
    p = AnthropicProvider(api_key="test-key")
    assert isinstance(p, LLMProvider)
    assert p.name == "anthropic"


def test_convert_messages_simple():
    sys_text, api = _convert_messages(
        [Message(role="system", content="you are X"), Message(role="user", content="hi")]
    )
    assert sys_text == "you are X"
    assert api == [{"role": "user", "content": "hi"}]


def test_convert_messages_with_tool_call():
    msgs = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content="let me check",
            tool_calls=[ToolCallRequest(name="ls", arguments={"path": "."}, id="t1")],
        ),
        Message(role="tool", name="ls", tool_call_id="t1", content='{"entries": []}'),
    ]
    sys_text, api = _convert_messages(msgs)
    assert sys_text == ""
    assert api[0]["role"] == "user"
    assert api[1]["role"] == "assistant"
    blocks = api[1]["content"]
    assert any(b["type"] == "text" and b["text"] == "let me check" for b in blocks)
    assert any(b["type"] == "tool_use" and b["name"] == "ls" for b in blocks)
    assert api[2]["role"] == "user"
    tool_results = api[2]["content"]
    assert tool_results[0]["type"] == "tool_result"
    assert tool_results[0]["tool_use_id"] == "t1"


def test_parse_response_text_and_tool():
    raw = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "x1", "name": "echo", "input": {"x": 1}},
        ]
    }
    resp = _parse_response(raw)
    assert resp.text == "hello"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "echo"
    assert resp.tool_calls[0].arguments == {"x": 1}


def test_chat_missing_api_key_raises():
    p = AnthropicProvider(api_key="")
    import pytest

    from hyusk.core.errors import ProviderError

    with pytest.raises(ProviderError):
        p.chat([])
