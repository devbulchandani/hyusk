"""WebSocket client used by the V2 CLI.

Speaks the same protocol as `hyusk.daemon.server`. Used by both the REPL
and one-shot modes. Falls back gracefully when the daemon is not running
(the caller decides whether to start an in-process agent instead).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect

from ..core.errors import HyuskError
from ..daemon.server import _port_open


@dataclass
class EventMessage:
    event: str
    data: dict[str, Any]


@dataclass
class RunOutcome:
    session_id: str | None
    iterations: int
    text_chars: int
    events: list[EventMessage]
    error: str | None = None
    final_text: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


def daemon_reachable(host: str, port: int) -> bool:
    return _port_open(host, port)


async def _send(ws, payload: dict) -> None:
    await ws.send(json.dumps(payload))


async def _recv(ws) -> dict:
    raw = await ws.recv()
    return json.loads(raw)


async def run_over_daemon(
    *,
    host: str,
    port: int,
    input_text: str,
    session_id: str | None,
    model: str | None = None,
) -> RunOutcome:
    """Run a turn on the daemon and collect all events into a single outcome.

    Returns once the daemon sends `done` or `error`.
    """
    events: list[EventMessage] = []
    final_text_parts: list[str] = []
    sid: str | None = None
    iterations = 0
    text_chars = 0
    error: str | None = None

    async with connect(f"ws://{host}:{port}", ping_interval=None) as ws:
        await _send(
            ws,
            {"type": "run", "session_id": session_id or "new", "input": input_text, "model": model},
        )
        while True:
            msg = await _recv(ws)
            mtype = msg.get("type")
            if mtype == "event":
                ev = msg["event"]
                data = msg.get("data", {})
                events.append(EventMessage(event=ev, data=data))
                if ev == "agent.text":
                    delta = bool(data.get("delta"))
                    text = data.get("text", "")
                    if delta:
                        final_text_parts.append(text)
                    else:
                        # Non-streaming provider: only keep the latest full text.
                        if not final_text_parts:
                            final_text_parts.append(text)
            elif mtype == "done":
                sid = msg.get("session_id")
                iterations = int(msg.get("iterations", 0))
                text_chars = int(msg.get("text_chars", 0))
                break
            elif mtype == "error":
                error = msg.get("message") or "unknown error"
                break

    return RunOutcome(
        session_id=sid,
        iterations=iterations,
        text_chars=text_chars,
        events=events,
        error=error,
        final_text="".join(final_text_parts),
    )


async def list_sessions(host: str, port: int) -> list[dict]:
    async with connect(f"ws://{host}:{port}", ping_interval=None) as ws:
        await _send(ws, {"type": "list_sessions"})
        msg = await _recv(ws)
        if msg.get("type") != "sessions":
            raise HyuskError(f"unexpected response: {msg}")
        return msg.get("sessions", [])


def run_over_daemon_sync(**kwargs) -> RunOutcome:
    return asyncio.run(run_over_daemon(**kwargs))


def list_sessions_sync(host: str, port: int) -> list[dict]:
    return asyncio.run(list_sessions(host, port))


def parse_event_payload(payload: dict) -> EventMessage:
    return EventMessage(event=payload["event"], data=payload.get("data", {}))
