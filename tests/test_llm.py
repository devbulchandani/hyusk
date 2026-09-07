"""Tests for LLM layer."""

import pytest

from hyusk.llm.base import LLMResponse, StreamChunk
from hyusk.llm.messages import (
    create_tool_result_message,
    message_to_dict,
    messages_to_anthropic_format,
    messages_to_openai_format,
    truncate_messages,
)
from hyusk.llm.router import LLMRouter, ModelType
from hyusk.models import Message, MessageRole, ToolCall


def test_message_to_dict_simple():
    """Test converting simple message to dict."""
    msg = Message(role=MessageRole.USER, content="Hello")
    result = message_to_dict(msg)

    assert result["role"] == "user"
    assert result["content"] == "Hello"


def test_message_to_dict_multimodal():
    """Test converting multimodal message to dict."""
    from hyusk.models import MessageContent

    msg = Message(
        role=MessageRole.USER,
        content=[
            MessageContent(type="text", text="Look at this:"),
            MessageContent(type="image", image_url="http://example.com/image.png"),
        ],
    )
    result = message_to_dict(msg)

    assert result["role"] == "user"
    assert len(result["content"]) == 2
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "Look at this:"


def test_create_tool_result_message():
    """Test creating tool result message."""
    msg = create_tool_result_message(
        tool_call_id="call_123",
        result={"status": "success"},
    )

    assert msg.role == MessageRole.TOOL
    assert "success" in msg.text_content
    assert msg.metadata["tool_call_id"] == "call_123"


def test_create_tool_result_message_with_error():
    """Test creating tool result message with error."""
    msg = create_tool_result_message(
        tool_call_id="call_123",
        result=None,
        error="Something went wrong",
    )

    assert msg.role == MessageRole.TOOL
    assert "Error" in msg.text_content
    assert "Something went wrong" in msg.text_content


def test_truncate_messages():
    """Test message truncation."""
    messages = [Message(role=MessageRole.SYSTEM, content="System")]
    messages.extend([
        Message(role=MessageRole.USER, content=f"Message {i}")
        for i in range(10)
    ])

    truncated = truncate_messages(messages, max_messages=5)

    assert len(truncated) == 5
    # System message should be preserved
    assert truncated[0].role == MessageRole.SYSTEM
    # Should keep most recent messages
    assert "Message 9" in truncated[-1].text_content


def test_llm_response_creation():
    """Test LLM response creation."""
    response = LLMResponse(
        content="Hello!",
        tool_calls=[],
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5},
    )

    assert response.has_content
    assert not response.has_tool_calls
    assert response.stop_reason == "end_turn"
    assert response.usage["input_tokens"] == 10


def test_llm_response_with_tool_calls():
    """Test LLM response with tool calls."""
    tool_call = ToolCall(
        tool_name="get_weather",
        arguments={"location": "San Francisco"},
    )

    response = LLMResponse(
        content=None,
        tool_calls=[tool_call],
    )

    assert not response.has_content
    assert response.has_tool_calls
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].tool_name == "get_weather"


def test_stream_chunk():
    """Test stream chunk creation."""
    chunk = StreamChunk(content="Hello")
    assert chunk.content == "Hello"
    assert not chunk.is_final

    final_chunk = StreamChunk(stop_reason="end_turn", is_final=True)
    assert final_chunk.is_final
    assert final_chunk.stop_reason == "end_turn"


def test_llm_router_model_selection():
    """Test LLM router model type selection."""
    router = LLMRouter()

    # Test model selection
    assert router.select_model_for_task(needs_vision=True) == ModelType.VISION
    assert router.select_model_for_task(needs_coding=True) == ModelType.CODING
    assert router.select_model_for_task(needs_speed=True) == ModelType.FAST
    assert router.select_model_for_task() == ModelType.DEFAULT


def test_anthropic_format_conversion():
    """Test converting messages to Anthropic format."""
    messages = [
        Message(role=MessageRole.SYSTEM, content="You are helpful"),
        Message(role=MessageRole.USER, content="Hello"),
        Message(role=MessageRole.ASSISTANT, content="Hi there!"),
    ]

    anthropic_messages = messages_to_anthropic_format(messages)

    # System messages should be filtered out (handled separately)
    assert len(anthropic_messages) == 2
    assert anthropic_messages[0]["role"] == "user"
    assert anthropic_messages[1]["role"] == "assistant"


def test_openai_format_conversion():
    """Test converting messages to OpenAI format."""
    messages = [
        Message(role=MessageRole.SYSTEM, content="You are helpful"),
        Message(role=MessageRole.USER, content="Hello"),
        Message(role=MessageRole.ASSISTANT, content="Hi there!"),
    ]

    openai_messages = messages_to_openai_format(messages)

    # All messages should be included
    assert len(openai_messages) == 3
    assert openai_messages[0]["role"] == "system"
    assert openai_messages[1]["role"] == "user"
    assert openai_messages[2]["role"] == "assistant"
