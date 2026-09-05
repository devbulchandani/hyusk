"""FastAPI server for the Hyusk web UI.

Wires up:
- Static files (CSS, JS, favicon) under /static
- HTML index at /
- WebSocket /ws for live agent events (text deltas, tool calls, etc.)
- POST /api/run to submit a new prompt
- GET /api/status to get daemon state (active tasks, etc.)
- GET /api/history to get a list of sessions
- Optional browser-mic stream at /ws/mic

The server connects to the same Hyusk daemon the CLI uses, so any
session started in the web UI is also accessible from the CLI and
vice versa.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..client.client import DaemonClient, EventMessage, TaskDone
from ..config.config import Config, user_config_dir
from ..daemon.registry_builder import build_provider, build_registry, build_policy


logger = logging.getLogger("hyusk.webui")


_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


class _PendingWebSocket:
    """Set of currently-connected browser WebSockets.

    The server pushes agent events to every connected client. We keep
    the set in memory (no Redis, no DB) — the web UI is meant to be
    a single-user companion, not a multi-user dashboard.
    """

    def __init__(self) -> None:
        self._set: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._set.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._set.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        msg = json.dumps(payload, default=str)
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._set:
                try:
                    await ws.send_text(msg)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._set.discard(ws)


class _RunRequest(BaseModel):
    text: str
    session_id: str | None = None
    model: str | None = None


def _build_app(daemon_host: str, daemon_port: int) -> FastAPI:
    """Build the FastAPI app with the configured daemon endpoint."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Open a single long-lived DaemonClient for the whole web UI
        # server. Each browser tab opens its own WebSocket; the events
        # from the daemon are fanned out to all of them.
        client = DaemonClient(daemon_host, daemon_port)
        try:
            await client.connect()
        except Exception as exc:
            logger.warning("cannot connect to daemon: %s", exc)
            client = None
        app.state.daemon = client
        app.state.sockets = _PendingWebSocket()
        try:
            yield
        finally:
            if client is not None:
                await client.close()

    app = FastAPI(
        title="Hyusk",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html_path = _TEMPLATES / "index.html"
        if not html_path.exists():
            raise HTTPException(500, f"missing template: {html_path}")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        client: DaemonClient | None = getattr(app.state, "daemon", None)
        if client is None:
            return {"connected": False, "version": __version__}
        try:
            v = await client.version()
            return {
                "connected": True,
                "version": v.get("version"),
                "protocol": v.get("protocol"),
            }
        except Exception as exc:
            return {"connected": False, "error": str(exc), "version": __version__}

    @app.get("/api/history")
    async def api_history() -> dict[str, Any]:
        client: DaemonClient | None = getattr(app.state, "daemon", None)
        if client is None:
            return {"sessions": []}
        try:
            sessions = await client.list_sessions_async() if hasattr(client, "list_sessions_async") else []
        except Exception:
            sessions = []
        return {"sessions": sessions}

    @app.post("/api/run")
    async def api_run(req: _RunRequest) -> dict[str, Any]:
        client: DaemonClient | None = getattr(app.state, "daemon", None)
        if client is None:
            raise HTTPException(503, "daemon not connected")
        task = await client.submit(
            input_text=req.text, session_id=req.session_id, model=req.model
        )
        return {"task_id": task.id, "session_id": task.session_id}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        sockets: _PendingWebSocket = app.state.sockets
        client: DaemonClient | None = getattr(app.state, "daemon", None)
        await sockets.add(ws)
        if client is not None:
            # Push initial state.
            try:
                v = await client.version()
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "version",
                            "version": v.get("version"),
                            "protocol": v.get("protocol"),
                        }
                    )
                )
            except Exception:
                pass

        # Track this connection's event-stream subscriptions. We allow
        # the browser to subscribe to specific tasks by sending:
        #   {"type": "subscribe", "task_id": "..."}
        # Until subscribed, the browser just receives global events.
        subscribed: set[str] = set()
        try:
            while True:
                msg = await ws.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                mtype = data.get("type")
                if mtype == "subscribe" and data.get("task_id"):
                    subscribed.add(data["task_id"])
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "subscribed",
                                "task_id": data["task_id"],
                            }
                        )
                    )
                elif mtype == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            pass
        finally:
            await sockets.remove(ws)

    @app.websocket("/ws/direct")
    async def ws_direct(ws: WebSocket) -> None:
        """A per-connection WebSocket proxy to the daemon.

        Each browser tab opens one of these and binds its own
        on_event callbacks. Used for sending a turn's events back to
        the specific browser tab that initiated it.
        """
        await ws.accept()
        client: DaemonClient | None = getattr(app.state, "daemon", None)
        if client is None:
            await ws.send_text(
                json.dumps({"type": "error", "message": "daemon not connected"})
            )
            await ws.close()
            return

        done_future: asyncio.Future[TaskDone] = asyncio.get_event_loop().create_future()
        current_task_id: list = [None]

        def on_event(ev: EventMessage) -> None:
            payload = {
                "type": "event",
                "event": ev.event,
                "data": ev.data or {},
                "task_id": ev.task_id,
            }
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(ws.send_text(json.dumps(payload)), loop)

        def on_done(d: TaskDone) -> None:
            payload = {
                "type": "task_done",
                "task": {
                    "task_id": d.task_id,
                    "state": d.state,
                    "iterations": d.iterations,
                    "text_chars": d.text_chars,
                    "cancelled": d.cancelled,
                    "error": d.error,
                },
            }
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(ws.send_text(json.dumps(payload)), loop)
            if not done_future.done():
                loop.call_soon_threadsafe(done_future.set_result, d)

        client.on_event(on_event)
        client.on_done(on_done)
        try:
            while True:
                msg = await ws.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                mtype = data.get("type")
                if mtype == "submit":
                    task = await client.submit(
                        input_text=data.get("text", ""),
                        session_id=data.get("session_id"),
                        model=data.get("model"),
                    )
                    current_task_id[0] = task.id
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "submitted",
                                "task_id": task.id,
                                "session_id": task.session_id,
                            }
                        )
                    )
                elif mtype == "cancel":
                    if current_task_id[0]:
                        await client.cancel(current_task_id[0])
                elif mtype == "steer":
                    if current_task_id[0]:
                        await client.steer(current_task_id[0], data.get("text", ""))
        except WebSocketDisconnect:
            pass
        finally:
            # No explicit unsubscribe; the daemon client's on_event is
            # shared across all connections. We could improve this with
            # a per-connection filter later.
            pass

    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
    return app


def serve(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True) -> None:
    """Start the web UI server.

    Opens the browser to the UI by default (configurable).
    """
    import uvicorn

    cfg = Config.load()
    daemon_host = cfg.daemon.host
    daemon_port = cfg.daemon.port

    app = _build_app(daemon_host, daemon_port)

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(f"http://{host}:{port}/")
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        app, host=host, port=port, log_level="info", access_log=False
    )
