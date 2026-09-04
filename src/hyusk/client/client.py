"""WebSocket client used by the V2/V3 CLI.

V3: supports submit/cancel/steer/list_tasks plus the routing of `ask`
decisions back to the daemon.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.asyncio.client import connect

from ..core.errors import HyuskError
from ..daemon.server import _port_open


@dataclass
class EventMessage:
    task_id: str | None
    event: str
    data: dict


@dataclass
class TaskDone:
    task_id: str
    state: str
    iterations: int
    text_chars: int
    cancelled: bool
    error: str | None = None


@dataclass
class PendingAsk:
    ask_id: str
    task_id: str
    tool: str
    arguments: dict


@dataclass
class Task:
    id: str
    session_id: str


# Callback types
EventCallback = Callable[[EventMessage], None]
AskCallback = Callable[[PendingAsk], bool]
DoneCallback = Callable[[TaskDone], None]


def daemon_reachable(host: str, port: int) -> bool:
    return _port_open(host, port)


# ---- high-level: one-shot ----


@dataclass
class RunOutcome:
    task_id: str | None
    session_id: str | None
    state: str
    iterations: int
    text_chars: int
    cancelled: bool
    error: str | None
    events: list[EventMessage]
    final_text: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and not self.cancelled


async def run_over_daemon(
    *,
    host: str,
    port: int,
    input_text: str,
    session_id: str | None = None,
    model: str | None = None,
    ask_callback: AskCallback | None = None,
) -> RunOutcome:
    """Submit a task and block until completion, collecting all events."""
    events: list[EventMessage] = []
    final_text_parts: list[str] = []
    task_id: str | None = None
    session_id_out: str | None = None
    iterations = 0
    text_chars = 0
    state = ""
    cancelled = False
    error: str | None = None

    async with connect(f"ws://{host}:{port}", ping_interval=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "run",
                    "session_id": session_id or "new",
                    "input": input_text,
                    "model": model,
                }
            )
        )
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "task":
                task_id = msg["task_id"]
                session_id_out = msg["session_id"]
            elif mtype == "event":
                ev = EventMessage(
                    task_id=msg.get("task_id"),
                    event=msg.get("event", ""),
                    data=msg.get("data", {}) or {},
                )
                events.append(ev)
                if ev.event == "agent.text":
                    text = ev.data.get("text", "")
                    if ev.data.get("delta"):
                        final_text_parts.append(text)
                    elif not final_text_parts:
                        final_text_parts.append(text)
            elif mtype == "ask":
                if ask_callback:
                    ask = PendingAsk(
                        ask_id=msg["ask_id"],
                        task_id=msg["task_id"],
                        tool=msg["tool"],
                        arguments=msg.get("arguments", {}) or {},
                    )
                    granted = ask_callback(ask)
                else:
                    granted = False
                await ws.send(json.dumps({"type": "grant", "ask_id": msg["ask_id"], "granted": granted}))
            elif mtype == "task_done":
                state = msg.get("state", "done")
                iterations = int(msg.get("iterations", 0))
                text_chars = int(msg.get("text_chars", 0))
                cancelled = bool(msg.get("cancelled", False))
                error = msg.get("error")
                break
            elif mtype == "error":
                error = msg.get("message") or "unknown error"
                break

    return RunOutcome(
        task_id=task_id,
        session_id=session_id_out,
        state=state,
        iterations=iterations,
        text_chars=text_chars,
        cancelled=cancelled,
        error=error,
        events=events,
        final_text="".join(final_text_parts),
    )


# ---- low-level: persistent client (for the REPL) ----


class DaemonClient:
    """Persistent WebSocket connection. Used by the REPL to talk to the
    daemon without reconnecting per turn."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._ws: Any = None
        self._reader_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Event listeners. We use `Callable[..., None]` instead of specific
        # callback types to keep `on_event`/`on_ask`/... interchangeable.
        self._on_event: list[Callable[..., None]] = []
        self._on_ask: list[Callable[..., None]] = []
        self._on_done: list[Callable[..., None]] = []
        self._on_error: list[Callable[..., None]] = []
        self._on_task_list: list[Callable[..., None]] = []
        # Pending futures for one-shot RPCs
        self._pending: dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        self._ws = await connect(f"ws://{self.host}:{self.port}", ping_interval=None)
        self._loop = asyncio.get_running_loop()
        self._reader_task = asyncio.create_task(self._reader())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle(msg)
        except websockets.ConnectionClosed:
            pass

    async def _handle(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "event":
            ev = EventMessage(
                task_id=msg.get("task_id"),
                event=msg.get("event", ""),
                data=msg.get("data", {}) or {},
            )
            for cb in list(self._on_event):
                try:
                    cb(ev)
                except Exception:
                    pass
        elif mtype == "ask":
            ask = PendingAsk(
                ask_id=msg["ask_id"],
                task_id=msg["task_id"],
                tool=msg["tool"],
                arguments=msg.get("arguments", {}) or {},
            )
            granted = False
            for cb in list(self._on_ask):
                try:
                    granted = bool(cb(ask)) or granted
                except Exception:
                    pass
            await self._send({"type": "grant", "ask_id": ask.ask_id, "granted": granted})
        elif mtype == "task_done":
            done = TaskDone(
                task_id=msg["task_id"],
                state=msg.get("state", "done"),
                iterations=int(msg.get("iterations", 0)),
                text_chars=int(msg.get("text_chars", 0)),
                cancelled=bool(msg.get("cancelled", False)),
                error=msg.get("error"),
            )
            for cb in list(self._on_done):
                try:
                    cb(done)
                except Exception:
                    pass
            # Resolve any future keyed on this task.
            fut = self._pending.pop(f"done:{done.task_id}", None)
            if fut and not fut.done():
                fut.get_loop().call_soon_threadsafe(fut.set_result, done)
        elif mtype == "error":
            err = msg.get("message") or "unknown error"
            for cb in list(self._on_error):
                try:
                    cb(err)
                except Exception:
                    pass
        elif mtype == "tasks":
            for cb in list(self._on_task_list):
                try:
                    cb(msg.get("tasks", []))
                except Exception:
                    pass
        elif mtype == "task":
            # New task started.
            fut = self._pending.pop("task", None)
            if fut and not fut.done():
                fut.get_loop().call_soon_threadsafe(
                    fut.set_result, Task(id=msg["task_id"], session_id=msg["session_id"])
                )

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def submit(
        self, *, input_text: str, session_id: str | None = None, model: str | None = None
    ) -> Task:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Task] = loop.create_future()
        self._pending["task"] = fut
        await self._send(
            {"type": "run", "session_id": session_id or "new", "input": input_text, "model": model}
        )
        return await asyncio.wait_for(fut, timeout=10.0)

    async def cancel(self, task_id: str) -> bool:
        await self._send({"type": "cancel", "task_id": task_id})
        return True

    async def steer(self, task_id: str, message: str) -> bool:
        await self._send({"type": "steer", "task_id": task_id, "input": message})
        return True

    async def list_tasks(self) -> list[dict]:
        await self._send({"type": "list_tasks"})
        # Wait for a "tasks" message. We add a one-shot handler in _handle.
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[list] = loop.create_future()

        def listener(payload: list) -> None:
            if not fut.done():
                fut.get_loop().call_soon_threadsafe(fut.set_result, payload)

        self._on_task_list.append(listener)
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        finally:
            try:
                self._on_task_list.remove(listener)
            except ValueError:
                pass

    async def wait_done(self, task_id: str, timeout: float | None = None) -> TaskDone:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[TaskDone] = loop.create_future()
        self._pending[f"done:{task_id}"] = fut
        return await asyncio.wait_for(fut, timeout=timeout)

    def on_event(self, cb: EventCallback) -> None:
        self._on_event.append(cb)

    def on_ask(self, cb: Callable[..., bool]) -> None:
        # Ask callback returns a bool; coerce to None for the listener list.
        def _wrap(ask: object) -> None:
            try:
                cb(ask)
            except Exception:
                pass
        self._on_ask.append(_wrap)

    def on_done(self, cb: DoneCallback) -> None:
        self._on_done.append(cb)

    def on_error(self, cb: Callable[[str], None]) -> None:
        self._on_error.append(cb)


def run_over_daemon_sync(**kwargs) -> RunOutcome:
    return asyncio.run(run_over_daemon(**kwargs))


def list_sessions_sync(host: str, port: int) -> list[dict]:
    async def _go() -> list[dict]:
        async with connect(f"ws://{host}:{port}", ping_interval=None) as ws:
            await ws.send(json.dumps({"type": "list_sessions"}))
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") != "sessions":
                raise HyuskError(f"unexpected response: {msg}")
            return msg.get("sessions", [])

    return asyncio.run(_go())
