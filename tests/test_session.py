"""Session persistence tests."""

from __future__ import annotations

from pathlib import Path

from hyusk.llm.provider import Message, ToolCallRequest
from hyusk.sessions.session import Session


def test_session_roundtrip(tmp_path: Path):
    s = Session.create()
    s.add(Message(role="user", content="hi"))
    s.add(
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCallRequest(name="echo", arguments={"x": "y"}, id="c1")],
        )
    )
    s.add(Message(role="tool", name="echo", tool_call_id="c1", content='{"echoed":"y"}'))

    s.save(str(tmp_path))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    loaded = Session.load(str(tmp_path), s.id)
    assert loaded.id == s.id
    assert len(loaded.messages) == 3
    assert loaded.messages[2].role == "tool"
    assert loaded.messages[2].name == "echo"


def test_list_sessions(tmp_path: Path):
    s = Session.create()
    s.save(str(tmp_path))
    listing = Session.list_sessions(str(tmp_path))
    assert any(item["id"] == s.id for item in listing)


def test_load_missing(tmp_path: Path):
    import pytest

    from hyusk.core.errors import FileNotFound

    with pytest.raises(FileNotFound):
        Session.load(str(tmp_path), "does-not-exist")
