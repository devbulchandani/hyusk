"""V4 daemon protocol tests: version, task_detail, list_tasks_all,
compact_session, discard_task, persistent task store."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from hyusk.agent.tasks import TaskInfo, TaskManager, TaskState, TaskStore
from hyusk.config.config import Config
from hyusk.daemon.server import DaemonContext
from hyusk.events.events import EventBus
from hyusk.permissions.policy import PermissionPolicy
from hyusk.sessions.store import SessionStore
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None, *, model=None, temperature=None):
        from hyusk.llm.provider import LLMResponse
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                text="checking",
                tool_calls=[_tc("echo", {"x": "hi"}, "c1")],
            )
        return LLMResponse(text="done")

    def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
        from hyusk.llm.provider import LLMChunk

        resp = self.chat(messages, tools, model=model, temperature=temperature)
        if resp.text:
            yield LLMChunk(text_delta=resp.text)
        yield LLMChunk(done=True, response=resp)


def _tc(name, args, id_):
    from hyusk.llm.provider import ToolCallRequest
    return ToolCallRequest(name=name, arguments=args, id=id_)


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
    task_store = TaskStore(base_dir=str(Path(cfg.session_dir).parent / "tasks"))
    tm = TaskManager(
        cfg=cfg,
        llm=_FakeLLM(),
        registry=reg,
        policy=PermissionPolicy(),
        session_dir=cfg.session_dir,
        store=task_store,
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
        task_store=task_store,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(ctx, host, port, send, stop_on):
    import websockets
    from websockets.asyncio.server import serve

    from hyusk.daemon.server import handle_client

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


def test_version_protocol(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "version"}],
            stop_on={"version"},
        )
    )
    assert any(r.get("type") == "version" for r in responses)
    v = next(r for r in responses if r.get("type") == "version")
    assert v["protocol"] == 4
    assert v["version"] == "0.4.0"


def test_task_detail_after_run(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    # First run a task, capture task_id from the "task" message.
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "run", "session_id": "new", "input": "test"}],
            stop_on={"task_done"},
        )
    )
    task_msgs = [r for r in responses if r.get("type") == "task"]
    assert task_msgs, "no task message in run response"
    task_id = task_msgs[0]["task_id"]

    # Now ask for the task detail.
    detail_responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "task_detail", "task_id": task_id}],
            stop_on={"task_detail", "error"},
        )
    )
    detail = next(r for r in detail_responses if r.get("type") == "task_detail")
    assert detail["task"]["id"] == task_id
    # The transcript should have at least the user message.
    transcript = detail["task"].get("transcript", [])
    assert any(m.get("role") == "user" for m in transcript)


def test_discard_task(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "run", "session_id": "new", "input": "x"}],
            stop_on={"task_done"},
        )
    )
    task_id = next(r["task_id"] for r in responses if r.get("type") == "task")

    # Discard the task.
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "discard_task", "task_id": task_id}],
            stop_on={"discarded", "error"},
        )
    )
    assert any(r.get("type") == "discarded" for r in responses)


def test_list_tasks_all_includes_persisted(tmp_path: Path, daemon_context):
    host = "127.0.0.1"
    port = _free_port()
    # Pre-populate a task directly in the store.
    info = TaskInfo(
        id="persisted-task",
        session_id="s",
        state=TaskState.DONE,
        input="yesterday",
        created_at=1.0,
    )
    daemon_context.task_store.save(info)

    # Now list_tasks_all should include it.
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "list_tasks_all"}],
            stop_on={"tasks"},
        )
    )
    tasks = next(r["tasks"] for r in responses if r.get("type") == "tasks")
    ids = {t["id"] for t in tasks}
    assert "persisted-task" in ids


def test_compact_session_without_llm_creates_stub(tmp_path: Path, daemon_context):
    """Without a real LLM the daemon should still produce a session that
    records the compaction metadata."""
    host = "127.0.0.1"
    port = _free_port()
    # First create a session by running a task.
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "run", "session_id": "new", "input": "x"}],
            stop_on={"task_done"},
        )
    )
    sid = next(r["session_id"] for r in responses if r.get("type") == "task")

    # Compact it.
    responses = asyncio.run(
        _drive(
            daemon_context,
            host,
            port,
            [{"type": "compact_session", "session_id": sid}],
            stop_on={"compacted", "error"},
        )
    )
    assert any(r.get("type") == "compacted" for r in responses)
    compacted = next(r for r in responses if r.get("type") == "compacted")
    new_sid = compacted["new_session_id"]
    assert new_sid and new_sid != sid
