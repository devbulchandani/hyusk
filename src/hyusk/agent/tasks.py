"""Task manager: runs multiple agents concurrently.

Each user request becomes a `Task` that owns:
  - a thread running the agent loop
  - a session (JSON-persisted) that the agent reads/writes
  - an `Agent` with its own EventBus
  - an `EventStream` for forwarding events to transports

Multiple tasks run at the same time. They share:
  - the global `ToolRegistry` (read-only at runtime)
  - the global `LLMProvider` instance (each call is independent, so OK)
  - the on-disk session directory

Steering: any client can call `task.steer(message)` to inject a follow-up
user message. The agent loop will pick it up between tool calls.

Cancellation: any client can call `task.cancel()`. The agent loop checks
the cancel flag at safe points and returns a result with
`cancelled=True`.

State:
  - pending   (just created)
  - running   (thread active)
  - done      (completed normally)
  - cancelled (cancel() was called; final result has cancelled=True)
  - errored   (raised; final result has error set)

V3 design note: events are NOT piped through the agent's bus. Instead,
the Task has its own internal subscribers list. The watcher thread
consumes the EventStream and broadcasts events to that list. This avoids
feedback loops where the bus subscriber would re-publish events back
to itself.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.config import Config
from ..events.events import Event, EventBus
from ..llm.provider import LLMProvider, Message
from ..permissions.policy import PermissionPolicy
from ..sessions.session import Session
from ..tools.registry import ToolRegistry
from .loop import Agent, EventStream, events_to_messages

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum as StrEnum  # type: ignore[assignment]


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    ERRORED = "errored"
    # V4: task was running when the daemon restarted. The agent thread is
    # gone; the user can resume the session manually.
    INTERRUPTED = "interrupted"


def _msg_to_dict(m: Message) -> dict:
    """Serialize a Message to a JSON-safe dict for the task transcript."""
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in m.tool_calls
        ],
        "tool_call_id": m.tool_call_id,
        "name": m.name,
    }


@dataclass
class TaskInfo:
    """A snapshot of a task's state for serialization."""

    id: str
    session_id: str
    state: TaskState
    input: str
    created_at: float
    started_at: float | None = None
    ended_at: float | None = None
    text: str = ""
    iterations: int = 0
    error: str | None = None
    cancelled: bool = False
    transcript: list[dict] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "state": self.state.value,
            "input": self.input,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "text": self.text,
            "iterations": self.iterations,
            "error": self.error,
            "cancelled": self.cancelled,
            "transcript": self.transcript or [],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskInfo:
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            state=TaskState(data.get("state", "pending")),
            input=data.get("input", ""),
            created_at=data.get("created_at", 0.0),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            text=data.get("text", ""),
            iterations=int(data.get("iterations", 0)),
            error=data.get("error"),
            cancelled=bool(data.get("cancelled", False)),
            transcript=data.get("transcript"),
        )


class Task:
    """A single background agent run."""

    def __init__(
        self,
        *,
        task_id: str,
        session: Session,
        user_input: str,
        llm: LLMProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        grant_callback,
        model: str,
        max_iterations: int,
        on_state_change=None,
    ) -> None:
        self.id = task_id
        self.session = session
        self.user_input = user_input
        self._bus = EventBus()
        self.agent = Agent(
            llm=llm,
            registry=registry,
            policy=policy,
            bus=self._bus,
            model=model,
            max_iterations=max_iterations,
            grant_callback=grant_callback,
        )
        self._state = TaskState.PENDING
        self._state_lock = threading.Lock()
        self._info = TaskInfo(
            id=task_id,
            session_id=session.id,
            state=self._state,
            input=user_input,
            created_at=time.time(),
        )
        self._result_text = ""
        self._result_iterations = 0
        self._result_error: str | None = None
        self._result_cancelled = False
        self._done_event = threading.Event()
        self._stream: EventStream | None = None
        # External subscribers (the daemon\'s _forward_events uses this).
        # Kept separate from the agent bus to avoid feedback loops.
        self._subscribers: list[Any] = []
        self._sub_lock = threading.Lock()
        self._watcher: threading.Thread | None = None
        # V4: optional callback invoked on every state change. Used by
        # TaskManager to persist TaskInfo to disk.
        self._on_state_change = on_state_change

    # ---- lifecycle ----

    def start(self) -> None:
        self._set_state(TaskState.RUNNING)
        self._info.started_at = time.time()
        # EventStream runs the agent in its own thread.
        self._stream = events_to_messages(
            self.agent,
            list(self.session.messages),
            user_input=self.user_input,
        )
        # Spin up a watcher thread that consumes events and notifies subscribers.
        self._watcher = threading.Thread(target=self._consume, daemon=True)
        self._watcher.start()

    def _consume(self) -> None:
        assert self._stream is not None
        try:
            for ev in self._stream:
                self._broadcast(ev)
        except Exception as exc:  # noqa: BLE001
            from ..core.errors import AgentLoopLimit

            if isinstance(exc, AgentLoopLimit):
                self._result_error = f"{type(exc).__name__}: {exc}"
                self._set_state(TaskState.ERRORED)
            else:
                self._result_error = f"{type(exc).__name__}: {exc}"
                self._set_state(TaskState.ERRORED)
            self._info.error = self._result_error
            self._info.ended_at = time.time()
            self._done_event.set()
            return
        result = self._stream.result
        if result is not None:
            self._result_text = result.text
            self._result_iterations = result.iterations
            # Update the session BEFORE changing state so any callback
            # (e.g. the TaskStore snapshot) sees the final messages.
            self.session.messages = list(result.session_messages)
            if result.cancelled:
                self._set_state(TaskState.CANCELLED)
                self._result_cancelled = True
            elif result.error:
                self._set_state(TaskState.ERRORED)
                self._result_error = result.error
            else:
                self._set_state(TaskState.DONE)
            try:
                self.session.save_self()
            except Exception:
                pass
        else:
            self._set_state(TaskState.DONE)
        self._info.text = self._result_text
        self._info.iterations = self._result_iterations
        self._info.error = self._result_error
        self._info.ended_at = time.time()

        # Final aggregator event so transports can render a single summary.
        self._broadcast(
            Event(
                type=self._state_event_type(),
                data={
                    "task_id": self.id,
                    "session_id": self.session.id,
                    "iterations": self._result_iterations,
                    "text_chars": len(self._result_text),
                    "cancelled": self._result_cancelled,
                    "error": self._result_error,
                },
            )
        )
        self._done_event.set()

    def _state_event_type(self):
        from ..events.events import EventType
        if self._state in (TaskState.DONE, TaskState.CANCELLED):
            return EventType.AGENT_COMPLETED
        return EventType.AGENT_ERROR

    def _set_state(self, state: TaskState) -> None:
        with self._state_lock:
            self._state = state
            self._info.state = state
        if self._on_state_change is not None:
            try:
                self._on_state_change(self)
            except Exception:
                pass

    # ---- public API ----

    def steer(self, message: str) -> None:
        self.agent.inject_steering(message)

    def cancel(self) -> None:
        self.agent.cancel()
        with self._state_lock:
            if self._state in (TaskState.PENDING, TaskState.RUNNING):
                self._state = TaskState.CANCELLED
                self._info.state = TaskState.CANCELLED
                self._info.ended_at = time.time()
        self._done_event.set()

    def events(self):
        """Return a (queue, unsubscribe) pair. The queue receives every event
        the agent publishes, including the final AGENT_COMPLETED/AGENT_ERROR.

        The subscriber is registered on the Task\'s own list (not the agent
        bus directly) and is fed by the Task\'s watcher thread. This avoids
        feedback loops between the EventStream and the Task.

        Safe to call BEFORE the task starts (events queue up internally).
        """
        import queue

        q: queue.Queue[Event] = queue.Queue()

        def on_event(ev: Event) -> None:
            try:
                q.put_nowait(ev)
            except Exception:
                pass

        with self._sub_lock:
            self._subscribers.append(on_event)

        def unsubscribe() -> None:
            with self._sub_lock:
                try:
                    self._subscribers.remove(on_event)
                except ValueError:
                    pass

        return q, unsubscribe

    def info(self) -> TaskInfo:
        with self._state_lock:
            return TaskInfo(
                id=self._info.id,
                session_id=self._info.session_id,
                state=self._info.state,
                input=self._info.input,
                created_at=self._info.created_at,
                started_at=self._info.started_at,
                ended_at=self._info.ended_at,
                text=self._result_text,
                iterations=self._result_iterations,
                error=self._result_error,
                cancelled=self._result_cancelled,
            )

    def result(self, timeout: float | None = None) -> TaskInfo | None:
        if not self._done_event.wait(timeout=timeout):
            return None
        return self.info()

    # ---- internals ----

    def _broadcast(self, ev: Event) -> None:
        with self._sub_lock:
            subs = list(self._subscribers)
        for s in subs:
            try:
                s(ev)
            except Exception:
                pass


class TaskStore:
    """Thread-safe persistent storage of TaskInfo records (V4).

    Tasks are written to `<base_dir>/<task_id>.json` so the daemon can
    restore state across restarts. On startup, the daemon calls
    `restore()` which loads any persisted tasks that were running and
    marks them as `interrupted`.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, task_id: str) -> Path:
        safe = "".join(c for c in task_id if c.isalnum() or c in "-_")
        return Path(self.base_dir) / f"{safe}.json"

    def save(self, info: TaskInfo) -> None:
        path = self._path(info.id)
        tmp = path.with_suffix(".tmp")
        with self._lock:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(info.to_dict(), f, indent=2, default=str)
            os.replace(tmp, path)

    def load(self, task_id: str) -> TaskInfo | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return TaskInfo.from_dict(json.load(f))

    def list(self) -> list[TaskInfo]:
        out: list[TaskInfo] = []
        with self._lock:
            for p in Path(self.base_dir).glob("*.json"):
                try:
                    with p.open("r", encoding="utf-8") as f:
                        out.append(TaskInfo.from_dict(json.load(f)))
                except Exception:
                    continue
        out.sort(key=lambda t: t.created_at, reverse=True)
        return out

    def delete(self, task_id: str) -> None:
        path = self._path(task_id)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


class TaskManager:
    """Owns all background tasks. Thread-safe.

    V4: optionally persists TaskInfo records to a TaskStore so the daemon
    can restore state across restarts. On startup, the daemon calls
    `restore()` which loads any persisted tasks that were running and
    marks them as `interrupted` (we cannot auto-resume a thread).
    """

    def __init__(
        self,
        *,
        cfg: Config,
        llm: LLMProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        session_dir: str,
        grant_callback=None,
        store: TaskStore | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm = llm
        self._registry = registry
        self._policy = policy
        self._session_dir = session_dir
        self._grant_callback = grant_callback
        self._store = store
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        input_text: str,
        session: Session,
        pre_subscribers: list | None = None,
    ) -> Task:
        """Submit a new task.

        pre_subscribers: a list of callables to register on the task before
        it starts. Each callable is called with every Event the agent emits.
        Used by the daemon so it can register the event-forwarder before
        the agent begins running.
        """
        task_id = uuid.uuid4().hex
        task = Task(
            task_id=task_id,
            session=session,
            user_input=input_text,
            llm=self._llm,
            registry=self._registry,
            policy=self._policy,
            grant_callback=self._grant_callback,
            model=self._cfg.llm.model,
            max_iterations=self._cfg.agent.max_iterations,
            on_state_change=self._on_task_state_change if self._store else None,
        )
        with self._lock:
            self._tasks[task_id] = task
        if pre_subscribers:
            with task._sub_lock:  # noqa: SLF001
                task._subscribers.extend(pre_subscribers)  # noqa: SLF001
        if self._store is not None:
            self._store.save(self._snapshot(task))
        task.start()
        return task

    def _on_task_state_change(self, task: Task) -> None:
        """Hook called by Task on every state transition."""
        if self._store is not None:
            self._store.save(self._snapshot(task))

    def _snapshot(self, task: Task) -> TaskInfo:
        info = task.info()
        # Capture a transcript of the current messages so we can inspect
        # the task after a restart.
        try:
            transcript = [_msg_to_dict(m) for m in task.session.messages]
        except Exception:
            transcript = []
        return TaskInfo(
            id=info.id,
            session_id=info.session_id,
            state=info.state,
            input=info.input,
            created_at=info.created_at,
            started_at=info.started_at,
            ended_at=info.ended_at,
            text=info.text,
            iterations=info.iterations,
            error=info.error,
            cancelled=info.cancelled,
            transcript=transcript,
        )

    def restore(self) -> int:
        """Reload persisted tasks and mark any that were running as
        `interrupted`. Returns the number of tasks restored."""
        if self._store is None:
            return 0
        loaded = self._store.list()
        restored = 0
        for info in loaded:
            if info.state in (TaskState.RUNNING, TaskState.PENDING):
                info.state = TaskState.INTERRUPTED
                info.error = (info.error or "") + " [interrupted by daemon restart]"
                self._store.save(info)
            restored += 1
        return restored

    def delete(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
        if t is None:
            # Even if no in-memory task, the record may be on disk.
            if self._store is not None:
                self._store.delete(task_id)
            return True
        t.cancel()
        if self._store is not None:
            self._store.delete(task_id)
        return True

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[TaskInfo]:
        with self._lock:
            tasks = list(self._tasks.values())
        return [t.info() for t in tasks]

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
        if not t:
            return False
        t.cancel()
        return True

    def steer(self, task_id: str, message: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
        if not t:
            return False
        t.steer(message)
        return True
