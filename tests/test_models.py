"""Tests for core models."""

import pytest
from datetime import datetime
from uuid import UUID

from hyusk.models import (
    Message,
    MessageRole,
    MessageContent,
    Task,
    TaskStatus,
    TaskType,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    Event,
    EventType,
)


def test_message_creation():
    """Test creating a message."""
    msg = Message(
        role=MessageRole.USER,
        content="Hello, Hyusk!"
    )

    assert msg.role == MessageRole.USER
    assert msg.text_content == "Hello, Hyusk!"
    assert isinstance(msg.id, UUID)
    assert isinstance(msg.created_at, datetime)


def test_message_with_multimodal_content():
    """Test message with multimodal content."""
    content = [
        MessageContent(type="text", text="Look at this:"),
        MessageContent(type="image", image_url="http://example.com/image.png"),
    ]

    msg = Message(
        role=MessageRole.USER,
        content=content
    )

    assert msg.text_content == "Look at this:"
    assert len(msg.content) == 2


def test_task_creation():
    """Test creating a task."""
    task = Task(
        type=TaskType.USER_COMMAND,
        description="Test task"
    )

    assert task.status == TaskStatus.QUEUED
    assert task.type == TaskType.USER_COMMAND
    assert task.description == "Test task"
    assert isinstance(task.id, UUID)


def test_tool_call_and_result():
    """Test tool call and result."""
    tool_call = ToolCall(
        tool_name="test_tool",
        arguments={"arg1": "value1"}
    )

    result = ToolResult(
        tool_call_id=tool_call.id,
        status=ToolResultStatus.SUCCESS,
        output={"result": "success"}
    )

    assert tool_call.tool_name == "test_tool"
    assert result.status == ToolResultStatus.SUCCESS
    assert result.tool_call_id == tool_call.id


def test_event_creation():
    """Test creating an event."""
    event = Event(
        type=EventType.TASK_CREATED,
        data={"task_id": "123"}
    )

    assert event.type == EventType.TASK_CREATED
    assert event.data["task_id"] == "123"
    assert isinstance(event.id, UUID)
