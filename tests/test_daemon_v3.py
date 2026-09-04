"""V3 daemon protocol tests: list_tasks, cancel, steer, ask routing."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from hyusk.agent.tasks import TaskManager
from hyusk.config.config import Config
from hyusk.daemon.server import DaemonContext
from hyusk.events.events import EventBus
from hyusk.permissions.policy import PermissionPolicy
from hyusk.sessions.store import SessionStore
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


class FakeProvider:
    """Simple provider that returns one tool call then done."""

    def __init__(self) -> None:
        self.calls = 0
        self.lock = asyncio.Lock() if False else __import__("threading").Lock()

    def chat(self, messages, tools=None, *, model=None, temperature=None):
        self.calls += 1
        if self.calls == 1:
            return _make_response(
                tool_calls=[_tc("echo", {"x": "hi"}, "c1")],
            )
        return _make_response(text="done")

    def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
        from hyusk.llm.provider import LLMChunk

        resp = self.chat(messages, tools, model=model, temperature=temperature)
        if resp.text:
            yield LLMChunk(text_delta=resp.text)
        yield LLMChunk(done=True, response=resp)


def _tc(name, args, id_):
    from hyusk.llm.provider import ToolCallRequest
    return ToolCallRequest(name=name, arguments=args, id=id_)


def _make_response(text="", tool_calls=None):
    from hyusk.llm.provider import LLMResponse
    return LLMResponse(text=text, tool_calls=tool_calls or [])


def _echo_tool():
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
    from hyusk.llm.provider import LLMProvider

    class _FakeLLM(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            self._p = FakeProvider()

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            return self._p.chat(messages, tools, model=model, temperature=temperature)

        def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
            return self._p.chat_stream(messages, tools, model=model, temperature=temperature)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HYUSK_LLM_API_KEY", "fake")
    cfg = Config.load()
    cfg.session_dir = str(tmp_path / "sessions")
    Path(cfg.session_dir).mkdir(parents=True, exist_ok=True)
    reg = ToolRegistry()
    reg.register(_echo_tool())
    store = SessionStore(base_dir=cfg.session_dir)
    tm = TaskManager(
        cfg=cfg,
        llm=_FakeLLM(),
        registry=reg,
        policy=PermissionPolicy(),
        session_dir=cfg.session_dir,
    )
    return DaemonContext(
        cfg=cfg,
        registry=reg,
        policy=PermissionPolicy(),
        llm=_FakeLLM(),
        bus=EventBus(),
        session_dir=cfg.session_dir,
        task_manager=tm,
        store=store,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(ctx, host: str, port: int, send: list[dict], stop_on: set[str] | None = None) -> list[dict]:
    """Send messages and collect responses until we see one of `stop_on` types.

    Default `stop_on`: {"task_done", "error"}.
    """
    import websockets
    from websockets.asyncio.server import serve

    from hyusk.daemon.server import handle_client

    if stop_on is None:
        stop_on = {"task_done", "error"}

    responses: list[dict] = []
    async with serve(lambda ws: handle_client(ws, ctx), host, port):
        async with websockets.connect(f"ws://{host}:{port}", ping_interval=None) as ws:
            for msg in send:
                await ws.send(json.dumps(msg))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except TimeoutError:
                    break
                payload = json.loads(raw)
                responses.append(payload)
                if payload.get("type") in stop_on:
                    break
    return responses


def test_daemon_list_tasks_empty(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "list_tasks"}],
            stop_on={"tasks"},
        )
    )
    assert any(r.get("type") == "tasks" for r in responses)
    tasks = next(r["tasks"] for r in responses if r.get("type") == "tasks")
    assert tasks == []


def test_daemon_run_streams_events(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "run", "session_id": "new", "input": "test"}],
        )
    )
    types = [r.get("type") for r in responses]
    assert "task" in types
    assert "task_done" in types
    # The events stream should contain tool.started.
    events = [r for r in responses if r.get("type") == "event"]
    assert any(r["event"] == "tool.started" for r in events)
