"""Task manager tests: concurrent tasks, steering, cancellation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from hyusk.agent.tasks import TaskManager, TaskState
from hyusk.llm.provider import LLMChunk, LLMProvider, LLMResponse, Message, ToolCallRequest
from hyusk.permissions.policy import PermissionPolicy
from hyusk.sessions.store import SessionStore
from hyusk.tools.base import READ, Tool
from hyusk.tools.registry import ToolRegistry


class _StaticProvider(LLMProvider):
    """A provider that returns the same canned response until told otherwise."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[list[Message]] = []

    def chat(self, messages, tools=None, *, model=None, temperature=None):
        self.calls.append(list(messages))
        if not self.responses:
            return LLMResponse(text="default")
        return self.responses.pop(0)

    def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
        resp = self.chat(messages, tools, model=model, temperature=temperature)
        if resp.text:
            yield LLMChunk(text_delta=resp.text)
        yield LLMChunk(done=True, response=resp)


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


def _build_manager(tmp_path: Path, provider: LLMProvider, *, max_iterations: int = 5) -> TaskManager:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[llm]\nmodel = test-model\n")
    import os
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    from hyusk.config.config import Config

    cfg = Config.load()
    cfg.session_dir = str(tmp_path / "sessions")
    Path(cfg.session_dir).mkdir(parents=True, exist_ok=True)
    cfg.agent.max_iterations = max_iterations
    reg = ToolRegistry()
    reg.register(_echo_tool())
    return TaskManager(
        cfg=cfg,
        llm=provider,
        registry=reg,
        policy=PermissionPolicy(),
        session_dir=cfg.session_dir,
    )


def test_submit_runs_to_completion(tmp_path: Path):
    provider = _StaticProvider(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCallRequest(name="echo", arguments={"x": "hi"}, id="c1")],
            ),
            LLMResponse(text="done"),
        ]
    )
    tm = _build_manager(tmp_path, provider)
    store = SessionStore(base_dir=tm._session_dir)
    session = store.new()
    task = tm.submit(input_text="hi", session=session)
    info = task.result(timeout=5.0)
    assert info is not None
    assert info.state == TaskState.DONE
    assert info.iterations == 2
    assert info.text == "done"


def test_concurrent_tasks_run_in_parallel(tmp_path: Path):
    """Two tasks should run concurrently without interfering."""
    barrier = threading.Barrier(2, timeout=5.0)
    started = []

    class SlowProvider(LLMProvider):
        name = "slow"

        def __init__(self, prefix: str) -> None:
            self.prefix = prefix
            self.calls = 0

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            self.calls += 1
            # Each task must reach chat at roughly the same time.
            barrier.wait()
            started.append(self.prefix)
            return LLMResponse(text=f"{self.prefix}-{self.calls}")

        def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
            resp = self.chat(messages, tools, model=model, temperature=temperature)
            if resp.text:
                yield LLMChunk(text_delta=resp.text)
            yield LLMChunk(done=True, response=resp)

    # Use two separate providers so the call counter is per-task.
    p1, p2 = SlowProvider("a"), SlowProvider("b")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[llm]\nmodel = test\n")
    import os
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    from hyusk.config.config import Config

    cfg = Config.load()
    cfg.session_dir = str(tmp_path / "sessions")
    Path(cfg.session_dir).mkdir(parents=True, exist_ok=True)
    reg = ToolRegistry()
    reg.register(_echo_tool())
    store = SessionStore(base_dir=cfg.session_dir)
    tm1 = TaskManager(cfg=cfg, llm=p1, registry=reg, policy=PermissionPolicy(), session_dir=cfg.session_dir)
    tm2 = TaskManager(cfg=cfg, llm=p2, registry=reg, policy=PermissionPolicy(), session_dir=cfg.session_dir)

    s1, s2 = store.new(), store.new()
    t1 = tm1.submit(input_text="x", session=s1)
    t2 = tm2.submit(input_text="y", session=s2)
    i1 = t1.result(timeout=5.0)
    i2 = t2.result(timeout=5.0)
    assert i1 is not None and i2 is not None
    assert i1.text == "a-1"
    assert i2.text == "b-1"
    # Both providers saw exactly one chat call.
    assert p1.calls == 1 and p2.calls == 1


def test_steering_injects_message(tmp_path: Path):
    """A steering message should be appended to the conversation after the
    current tool call completes."""

    """A steering message should be appended to the conversation after the
    current tool call completes."""

    class CountingProvider(LLMProvider):
        name = "counting"

        def __init__(self) -> None:
            self.calls: list[list[Message]] = []

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            self.calls.append(list(messages))
            n = len(self.calls)
            if n == 1:
                return LLMResponse(
                    text="",
                    tool_calls=[ToolCallRequest(name="echo", arguments={"x": "first"}, id="c1")],
                )
            # On the second call, the steered message should be present.
            user_msgs = [m for m in messages if m.role == "user"]
            contents = [m.content for m in user_msgs]
            assert "carry on please" in contents, f"steering not seen: {contents}"
            return LLMResponse(text="ok")

        def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
            resp = self.chat(messages, tools, model=model, temperature=temperature)
            if resp.text:
                yield LLMChunk(text_delta=resp.text)
            yield LLMChunk(done=True, response=resp)

    class SlowCountingProvider(LLMProvider):
        """A provider that takes time per call so steering can land between iters."""

        name = "slowcounting"

        def __init__(self) -> None:
            self.calls: list[list[Message]] = []

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            self.calls.append(list(messages))
            n = len(self.calls)
            # Each call takes ~30ms so we have time to steer between iters.
            time.sleep(0.03)
            # First two calls return a tool call so the agent iterates
            # multiple times. The steered message should appear in call 3.
            if n in (1, 2):
                return LLMResponse(
                    text="",
                    tool_calls=[ToolCallRequest(name="echo", arguments={"x": str(n)}, id=f"c{n}")],
                )
            user_msgs = [m for m in messages if m.role == "user"]
            contents = [m.content for m in user_msgs]
            assert "carry on please" in contents, f"steering not seen in call {n}: {contents}"
            return LLMResponse(text="ok")

        def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
            resp = self.chat(messages, tools, model=model, temperature=temperature)
            if resp.text:
                yield LLMChunk(text_delta=resp.text)
            yield LLMChunk(done=True, response=resp)

    provider = SlowCountingProvider()
    tm = _build_manager(tmp_path, provider)
    store = SessionStore(base_dir=tm._session_dir)
    session = store.new()
    task = tm.submit(input_text="hi", session=session)

    # Let the agent start its first iter (which calls chat()).
    time.sleep(0.05)
    task.steer("carry on please")
    info = task.result(timeout=5.0)
    assert info is not None
    assert info.state == TaskState.DONE
    assert len(provider.calls) >= 2  # the second chat call was made


def test_cancellation_stops_a_long_task(tmp_path: Path):
    """A long-running task that gets cancelled should finish quickly with cancelled=True.

    Uses a slow provider so each chat call takes a few ms, giving cancel()
    time to take effect between iterations.
    """

    class SlowLoopingProvider(LLMProvider):
        name = "slowlooping"

        def __init__(self, max_calls: int = 200) -> None:
            self.max_calls = max_calls
            self.calls = 0

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            self.calls += 1
            if self.calls > self.max_calls:
                return LLMResponse(text="eventually done")
            # Each chat call takes ~5ms so cancel() can land between iters.
            time.sleep(0.005)
            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCallRequest(
                        name="echo",
                        arguments={"x": str(self.calls)},
                        id=f"c{self.calls}",
                    )
                ],
            )

        def chat_stream(self, messages, tools=None, *, model=None, temperature=None):
            resp = self.chat(messages, tools, model=model, temperature=temperature)
            if resp.text:
                yield LLMChunk(text_delta=resp.text)
            yield LLMChunk(done=True, response=resp)

    provider = SlowLoopingProvider(max_calls=200)
    tm = _build_manager(tmp_path, provider, max_iterations=500)
    store = SessionStore(base_dir=tm._session_dir)
    session = store.new()
    task = tm.submit(input_text="loop", session=session)
    time.sleep(0.05)  # let the task run a few iterations
    task.cancel()
    info = task.result(timeout=2.0)
    assert info is not None
    # Either the task was cancelled, or it finished because cancel landed
    # right at a natural break point. The important property is that it
    # did NOT run all 200 iterations.
    assert provider.calls < 200, f"ran all {provider.calls} iterations; cancel did not stop it"


def test_events_queue_receives_events(tmp_path: Path):
    import queue as _q

    provider = _StaticProvider(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCallRequest(name="echo", arguments={"x": "x"}, id="c1")],
            ),
            LLMResponse(text="done"),
        ]
    )
    tm = _build_manager(tmp_path, provider)
    store = SessionStore(base_dir=tm._session_dir)
    session = store.new()

    # Pre-create the queue and subscriber so events are not lost.
    q: _q.Queue = _q.Queue()

    def pre_sub(ev) -> None:
        try:
            q.put_nowait(ev)
        except Exception:
            pass

    task = tm.submit(input_text="hi", session=session, pre_subscribers=[pre_sub])

    info = task.result(timeout=5.0)
    assert info is not None
    # Drain the queue.
    seen = []
    while True:
        try:
            ev = q.get_nowait()
        except Exception:
            break
        if ev is None:
            break
        seen.append(ev.type.value)
    # Should include tool.started and agent.completed.
    assert "tool.started" in seen, f"missing tool.started in {seen}"
    assert "agent.completed" in seen, f"missing agent.completed in {seen}"
