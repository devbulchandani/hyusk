"""Daemon end-to-end test using a fake LLM provider.

Spawns the daemon's WebSocket handler in-process against an ephemeral
port, sends a `run` message, and asserts the protocol is honored.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from hyusk.config.config import Config
from hyusk.daemon.server import DaemonContext, _port_open, handle_client
from hyusk.events.events import EventBus
from hyusk.llm.provider import LLMChunk, LLMProvider, LLMResponse, ToolCallRequest
from hyusk.permissions.policy import PermissionPolicy
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None, *, model=None, temperature=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                text="checking",
                tool_calls=[ToolCallRequest(name="echo", arguments={"x": "hi"}, id="c1")],
            )
        return LLMResponse(text="done")

    def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
        # Same behavior but streaming.
        resp = self.chat(messages, tools, model=model, temperature=temperature)
        if resp.text:
            yield from (LLMChunk(text_delta=resp.text),)
        yield LLMChunk(done=True, response=resp)


def _free_port() -> int:
    """Find an unused TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="echo",
        input_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        permission=READ,
        execute=lambda a: {"echoed": a["x"]},
    )


@pytest.fixture
def daemon_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HYUSK_LLM_API_KEY", "fake-key")
    cfg = Config.load()
    cfg.session_dir = str(tmp_path / "sessions")
    Path(cfg.session_dir).mkdir(parents=True, exist_ok=True)

    reg = ToolRegistry()
    reg.register(_echo_tool())
    ctx = DaemonContext(
        cfg=cfg,
        registry=reg,
        policy=PermissionPolicy(),
        llm=FakeProvider(),
        bus=EventBus(),
        session_dir=cfg.session_dir,
    )
    return ctx


async def _drive_daemon(ctx: DaemonContext, host: str, port: int, send: dict) -> list[dict]:
    """Start the daemon in a background thread, connect, send one msg, collect responses."""
    import websockets
    from websockets.asyncio.server import serve

    stop_event = asyncio.Event()
    responses: list[dict] = []

    async with serve(lambda ws: handle_client(ws, ctx), host, port):
        # Connect
        async with websockets.connect(f"ws://{host}:{port}", ping_interval=None) as ws:
            await ws.send(json.dumps(send))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except TimeoutError:
                    break
                msg = json.loads(raw)
                responses.append(msg)
                if msg.get("type") in ("done", "error"):
                    break
        stop_event.set()

    return responses


def test_daemon_run_protocol(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive_daemon(
            daemon_context,
            host,
            port,
            {"type": "run", "session_id": "new", "input": "test"},
        )
    )
    # We expect: agent.started, agent.thinking, agent.text, tool.started, tool.completed,
    # agent.text (final), agent.completed, done
    types = [r.get("type") for r in responses]
    assert types[-1] == "done"
    assert "event" in types
    assert any(r.get("event") == "tool.started" for r in responses if r.get("type") == "event")
    assert any(r.get("event") == "tool.completed" for r in responses if r.get("type") == "event")
    assert any(r.get("event") == "agent.completed" for r in responses if r.get("type") == "event")
    # session should have been created
    assert "session_id" in responses[-1]


def test_daemon_ping(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive_daemon(daemon_context, host, port, {"type": "ping"})
    )
    assert any(r.get("type") == "pong" for r in responses)


def test_daemon_unknown_type(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive_daemon(daemon_context, host, port, {"type": "garbage"})
    )
    assert any(r.get("type") == "error" for r in responses)


def test_port_open_helper():
    port = _free_port()
    # Initially nothing is listening.
    assert _port_open("127.0.0.1", port) is False
    # Open a listening socket.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    try:
        assert _port_open("127.0.0.1", port) is True
    finally:
        s.close()
