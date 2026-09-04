"""Hyusk daemon: WebSocket server hosting the agent, sessions, and events.

V2: runs an asyncio WebSocket server. Each `run` message executes an agent
turn in a background thread and streams events back to the client.

V3: concurrent tasks.
  - `run` returns a `task_id` immediately and runs in the background.
  - `cancel <task_id>` stops a task.
  - `steer <task_id> <message>` injects a follow-up user message.
  - `list_tasks` shows all tasks (running + recently finished).
  - `ask` decisions are routed back to the client that submitted the task.
  - Events are tagged with `task_id` so clients can multiplex.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from ..agent.loop import Agent
from ..agent.tasks import TaskManager, TaskState
from ..config.config import Config
from ..core.errors import HyuskError
from ..events.events import Event, EventBus
from ..llm.provider import LLMProvider
from ..permissions.policy import PermissionPolicy
from ..sessions.store import SessionStore
from ..tools.registry import ToolRegistry
from .registry_builder import build_policy, build_provider, build_registry

logger = logging.getLogger("hyusk.daemon")


@dataclass
class PendingAsk:
    task_id: str
    tool_name: str
    arguments: dict
    future: asyncio.Future[bool]


@dataclass
class ClientState:
    pending_asks: dict[str, PendingAsk] = field(default_factory=dict)


@dataclass
class DaemonContext:
    cfg: Config
    registry: ToolRegistry
    policy: PermissionPolicy
    llm: LLMProvider
    bus: EventBus
    session_dir: str
    task_manager: TaskManager
    store: SessionStore

    def new_agent(self) -> Agent:
        return Agent(
            llm=self.llm,
            registry=self.registry,
            policy=self.policy,
            bus=EventBus(),
            model=self.cfg.llm.model,
            max_iterations=self.cfg.agent.max_iterations,
        )


def pid_file() -> Path:
    return Path(Config.load().session_dir).parent / "daemon.pid"


def is_running() -> dict[str, Any] | None:
    pf = pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        try:
            pf.unlink()
        except OSError:
            pass
        return None
    return {"pid": pid, "pid_file": str(pf)}


def write_pid_file() -> None:
    pid_file().write_text(str(os.getpid()))


def clear_pid_file() -> None:
    pf = pid_file()
    try:
        pf.unlink()
    except OSError:
        pass


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


# ---- handler ----


async def handle_client(ws: ServerConnection, ctx: DaemonContext) -> None:
    peer = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
    logger.info("client connected: %s", peer)
    state = ClientState()
    forwarders: dict[str, threading.Thread] = {}
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "message": "invalid JSON"})
                continue
            try:
                await _dispatch(ws, ctx, state, msg, forwarders)
            except HyuskError as exc:
                await _send(ws, {"type": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("dispatch error")
                await _send(ws, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    except websockets.ConnectionClosed:
        pass
    finally:
        for t in forwarders.values():
            # Tell the thread to stop; it polls a flag.
            t.join(timeout=2.0)
        logger.info("client disconnected: %s", peer)


async def _send(ws: ServerConnection, payload: dict[str, Any]) -> None:
    try:
        await ws.send(json.dumps(payload, default=str))
    except websockets.ConnectionClosed:
        pass


def _ask_factory(loop: asyncio.AbstractEventLoop, ws: ServerConnection, state: ClientState, task_id: str):
    def grant(tool_name: str, arguments: dict) -> bool:
        fut: asyncio.Future[bool] = loop.create_future()
        ask_id = f"{task_id}.{tool_name}.{time.time()}"
        state.pending_asks[ask_id] = PendingAsk(
            task_id=task_id,
            tool_name=tool_name,
            arguments=arguments,
            future=fut,
        )
        asyncio.run_coroutine_threadsafe(
            _send(
                ws,
                {
                    "type": "ask",
                    "ask_id": ask_id,
                    "task_id": task_id,
                    "tool": tool_name,
                    "arguments": arguments,
                },
            ),
            loop,
        )
        return fut.result()

    return grant


async def _dispatch(
    ws: ServerConnection,
    ctx: DaemonContext,
    state: ClientState,
    msg: dict[str, Any],
    forwarders: dict[str, threading.Thread],
) -> None:
    mtype = msg.get("type")
    if mtype == "ping":
        await _send(ws, {"type": "pong"})
        return
    if mtype == "list_sessions":
        await _send(ws, {"type": "sessions", "sessions": ctx.store.list()})
        return
    if mtype == "load_session":
        try:
            sess = ctx.store.load(msg["id"])
            await _send(ws, {"type": "session", "session": sess.to_dict()})
        except HyuskError as exc:
            await _send(ws, {"type": "error", "message": str(exc)})
        return
    if mtype == "list_tasks":
        await _send(ws, {"type": "tasks", "tasks": [t.to_dict() for t in ctx.task_manager.list()]})
        return
    if mtype == "cancel":
        tid = msg.get("task_id")
        ok = ctx.task_manager.cancel(tid) if tid else False
        await _send(ws, {"type": "cancelled", "task_id": tid, "ok": ok})
        return
    if mtype == "steer":
        tid = msg.get("task_id")
        text = msg.get("input", "") or ""
        ok = ctx.task_manager.steer(tid, text) if tid else False
        await _send(ws, {"type": "steered", "task_id": tid, "ok": ok})
        return
    if mtype == "grant":
        ask_id = msg.get("ask_id")
        decision = bool(msg.get("granted", False))
        ask_id_str = str(ask_id) if ask_id is not None else ""
        pending: PendingAsk | None = state.pending_asks.pop(ask_id_str, None) if ask_id_str else None
        if pending is not None and not pending.future.done():
            pending.future.get_loop().call_soon_threadsafe(pending.future.set_result, decision)
        return
    if mtype == "run":
        await _submit(ws, ctx, state, msg, forwarders)
        return
    await _send(ws, {"type": "error", "message": f"unknown message type: {mtype}"})


async def _submit(
    ws: ServerConnection,
    ctx: DaemonContext,
    state: ClientState,
    msg: dict[str, Any],
    forwarders: dict[str, threading.Thread],
) -> None:
    input_text = msg.get("input", "") or ""
    requested_id = msg.get("session_id")

    if requested_id and requested_id != "new":
        try:
            session = ctx.store.load(requested_id)
        except HyuskError:
            session = ctx.store.new()
    else:
        session = ctx.store.new()

    # Pre-create the event mailbox and the subscriber so events fired
    # immediately after submit() are not lost.
    q: queue.Queue[Event | None] = queue.Queue()

    def pre_sub(ev: Event) -> None:
        try:
            q.put_nowait(ev)
        except Exception:
            pass

    # The agent thread emits events to the agent's bus. The Task\'s
    # watcher thread consumes the EventStream and broadcasts to subscribers.
    # Our pre_sub is one of those subscribers.
    loop = asyncio.get_running_loop()
    # We\'ll rebind the ask callback after we know the task id.

    task = ctx.task_manager.submit(
        input_text=input_text,
        session=session,
        pre_subscribers=[pre_sub],
    )
    # Replace the placeholder ask factory with one that knows the real id.
    real_grant = _ask_factory(loop, ws, state, task_id=task.id)
    task.agent.grant_callback = real_grant

    # Tell the client about the new task.
    await _send(
        ws,
        {
            "type": "task",
            "task_id": task.id,
            "session_id": session.id,
        },
    )

    # Spin up a forwarder thread that consumes the queue and pushes to
    # the asyncio loop.
    fwd = threading.Thread(
        target=_forwarder_thread,
        args=(loop, ws, task.id, session.id, q, ctx.task_manager),
        daemon=True,
    )
    fwd.start()
    forwarders[task.id] = fwd


def _forwarder_thread(
    loop: asyncio.AbstractEventLoop,
    ws: ServerConnection,
    task_id: str,
    session_id: str,
    q: queue.Queue[Event | None],
    tm: TaskManager,
) -> None:
    """Drains the event queue and forwards each event to the WebSocket.

    Runs on a background thread; uses run_coroutine_threadsafe to push
    work onto the asyncio loop.
    """
    task = tm.get(task_id)
    if task is None:
        return

    def post(payload: dict) -> None:
        # Each send is its own short-lived coroutine.
        asyncio.run_coroutine_threadsafe(_send(ws, payload), loop)

    while True:
        try:
            ev = q.get(timeout=0.5)
        except Exception:
            # Periodically check whether the task is done.
            if task._done_event.is_set() and q.empty():  # noqa: SLF001
                break
            continue
        if ev is None:
            break
        post(
            {
                "type": "event",
                "task_id": task_id,
                "session_id": session_id,
                "event": ev.type.value,
                "data": ev.data,
            }
        )

    # Drain any remaining events.
    while not q.empty():
        try:
            ev = q.get_nowait()
        except Exception:
            break
        if ev is None:
            break
        post(
            {
                "type": "event",
                "task_id": task_id,
                "session_id": session_id,
                "event": ev.type.value,
                "data": ev.data,
            }
        )

    info = task.info()
    post(
        {
            "type": "task_done",
            "task_id": task_id,
            "state": info.state.value,
            "iterations": info.iterations,
            "text_chars": len(info.text),
            "cancelled": info.state == TaskState.CANCELLED,
            "error": info.error,
        }
    )


# ---- entry ----


def build_context() -> DaemonContext:
    cfg = Config.load()
    registry = build_registry()
    policy = build_policy(cfg)
    llm = build_provider(cfg)
    store = SessionStore(base_dir=cfg.session_dir)
    task_manager = TaskManager(
        cfg=cfg,
        llm=llm,
        registry=registry,
        policy=policy,
        session_dir=cfg.session_dir,
        grant_callback=None,
    )
    return DaemonContext(
        cfg=cfg,
        registry=registry,
        policy=policy,
        llm=llm,
        bus=EventBus(),
        session_dir=cfg.session_dir,
        task_manager=task_manager,
        store=store,
    )


async def run_server(host: str, port: int) -> None:
    ctx = build_context()
    if _port_open(host, port):
        print(f"[hyusk daemon] port {port} already in use on {host}", file=sys.stderr)
        sys.exit(2)
    write_pid_file()
    logger.info("daemon starting on %s:%d (model=%s, provider=%s)",
                host, port, ctx.cfg.llm.model, ctx.cfg.llm.provider)
    stop = asyncio.Event()

    def _shutdown(*_args):
        logger.info("daemon shutting down")
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _shutdown)
        loop.add_signal_handler(signal.SIGTERM, _shutdown)
    except (NotImplementedError, RuntimeError):
        pass

    async with serve(lambda ws: handle_client(ws, ctx), host, port) as server:
        await stop.wait()
        server.close()


def serve_forever() -> None:
    logging.basicConfig(level=os.environ.get("HYUSK_LOG_LEVEL", "INFO"))
    cfg = Config.load()
    try:
        asyncio.run(run_server(cfg.daemon.host, cfg.daemon.port))
    finally:
        clear_pid_file()
