"""Hyusk daemon: WebSocket server hosting the agent, sessions, and events.

The daemon is the V2 transport. CLI clients (and future mobile/voice clients)
connect to it instead of running the agent in-process. The agent core, tool
registry, permission policy, and session store are unchanged from V1.

Protocol (JSON messages over WebSocket):

  Client -> Server:
    {"type": "run", "session_id": "<uuid|new>", "input": "...", "model": "..."}
    {"type": "list_sessions"}
    {"type": "load_session", "id": "..."}
    {"type": "ping"}

  Server -> Client:
    {"type": "event", "event": "agent.started|tool.started|...", "data": {...}}
    {"type": "done", "iterations": N, "text_chars": M, "session_id": "..."}
    {"type": "error", "message": "..."}
    {"type": "pong"}
    {"type": "sessions", "sessions": [{"id":..., "created_at":...}]}
    {"type": "session", "session": {"id":..., "messages":[...]}}

The daemon is meant to run as `hyusk daemon start`. PID file at the user
config dir so `hyusk daemon stop` can terminate it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from ..agent.loop import Agent, events_to_messages
from ..config.config import Config
from ..core.errors import HyuskError
from ..events.events import EventBus
from ..llm.provider import LLMProvider, Message
from ..permissions.policy import PermissionPolicy
from ..sessions.session import Session
from ..tools.registry import ToolRegistry
from .registry_builder import build_policy, build_provider, build_registry

logger = logging.getLogger("hyusk.daemon")


@dataclass
class DaemonContext:
    """Owns the agent and shared state for the lifetime of the daemon."""

    cfg: Config
    registry: ToolRegistry
    policy: PermissionPolicy
    llm: LLMProvider
    bus: EventBus
    session_dir: str

    def new_agent(self, *, grant_callback=None) -> Agent:
        # Fresh EventBus per session so concurrent clients don't interleave.
        return Agent(
            llm=self.llm,
            registry=self.registry,
            policy=self.policy,
            bus=EventBus(),
            model=self.cfg.llm.model,
            max_iterations=self.cfg.agent.max_iterations,
            grant_callback=grant_callback,
        )


# ---- pid file helpers ----


def pid_file() -> Path:
    return Path(Config.load().session_dir).parent / "daemon.pid"


def is_running() -> dict[str, Any] | None:
    """Return status dict if a daemon is running, else None."""
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
        # stale pidfile
        try:
            pf.unlink()
        except OSError:
            pass
        return None
    return {"pid": pid, "pid_file": str(pf)}


def write_pid_file() -> None:
    pf = pid_file()
    pf.write_text(str(os.getpid()))


def clear_pid_file() -> None:
    pf = pid_file()
    try:
        pf.unlink()
    except OSError:
        pass


# ---- port helpers ----


def _port_open(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
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
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "message": "invalid JSON"})
                continue
            try:
                await _dispatch(ws, ctx, msg)
            except HyuskError as exc:
                await _send(ws, {"type": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("dispatch error")
                await _send(ws, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    except websockets.ConnectionClosed:
        pass
    finally:
        logger.info("client disconnected: %s", peer)


async def _send(ws: ServerConnection, payload: dict[str, Any]) -> None:
    try:
        await ws.send(json.dumps(payload, default=str))
    except websockets.ConnectionClosed:
        pass


async def _dispatch(ws: ServerConnection, ctx: DaemonContext, msg: dict[str, Any]) -> None:
    mtype = msg.get("type")
    if mtype == "ping":
        await _send(ws, {"type": "pong"})
        return
    if mtype == "list_sessions":
        await _send(ws, {"type": "sessions", "sessions": Session.list_sessions(ctx.session_dir)})
        return
    if mtype == "load_session":
        try:
            sess = Session.load(ctx.session_dir, msg["id"])
            await _send(ws, {"type": "session", "session": sess.to_dict()})
        except HyuskError as exc:
            await _send(ws, {"type": "error", "message": str(exc)})
        return
    if mtype == "run":
        await _run_session(ws, ctx, msg)
        return
    await _send(ws, {"type": "error", "message": f"unknown message type: {mtype}"})


async def _run_session(ws: ServerConnection, ctx: DaemonContext, msg: dict[str, Any]) -> None:
    input_text = msg.get("input", "") or ""
    requested_id = msg.get("session_id")

    if requested_id and requested_id != "new":
        try:
            session = Session.load(ctx.session_dir, requested_id)
        except HyuskError:
            session = Session.create()
    else:
        session = Session.create()

    # Build an agent with an isolated bus, grant-all policy for the daemon
    # (the CLI is responsible for granting at the local terminal; the
    # daemon does not prompt). Future versions can route ask-decisions
    # back to the connected client.
    agent = ctx.new_agent(grant_callback=lambda name, args: True)

    messages: list[Message] = list(session.messages)
    stream = events_to_messages(agent, messages, user_input=input_text)

    try:
        async for ev in _aiter_events(stream):
            await _send(
                ws,
                {
                    "type": "event",
                    "event": ev.type.value,
                    "data": ev.data,
                },
            )
    except HyuskError as exc:
        await _send(ws, {"type": "error", "message": str(exc)})
        return

    result = stream.result
    if result is not None:
        session.messages = list(result.session_messages)
        session.save(ctx.session_dir)
        await _send(
            ws,
            {
                "type": "done",
                "session_id": session.id,
                "iterations": result.iterations,
                "text_chars": len(result.text),
            },
        )


async def _aiter_events(stream):
    """Bridge the sync EventStream iterator to async.

    Uses a queue fed by a reader thread so we never block the asyncio loop
    on the synchronous EventStream polling (which sleeps in 5ms ticks).
    """
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def reader() -> None:
        try:
            for ev in stream:
                loop.call_soon_threadsafe(q.put_nowait, ev)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while True:
        item = await q.get()
        if item is None:
            return
        yield item


# ---- entry ----


def build_context() -> DaemonContext:
    cfg = Config.load()
    return DaemonContext(
        cfg=cfg,
        registry=build_registry(),
        policy=build_policy(cfg),
        llm=build_provider(cfg),
        bus=EventBus(),
        session_dir=cfg.session_dir,
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
        # Windows / non-unix
        pass

    async with serve(lambda ws: handle_client(ws, ctx), host, port) as server:
        await stop.wait()
        server.close()


def serve_forever() -> None:
    """Synchronous entry point for `hyusk daemon start`."""
    logging.basicConfig(level=os.environ.get("HYUSK_LOG_LEVEL", "INFO"))
    cfg = Config.load()
    try:
        asyncio.run(run_server(cfg.daemon.host, cfg.daemon.port))
    finally:
        clear_pid_file()
