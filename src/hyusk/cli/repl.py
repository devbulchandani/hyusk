"""Interactive REPL.

Renders agent events to the terminal. Subscribes to the event bus rather
than calling into agent internals so a WebSocket/mobile client can reuse
the same agent.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from ..agent.loop import Agent
from ..core.errors import AgentLoopLimit, HyuskError
from ..events.events import Event, EventBus, EventType
from ..sessions.session import Session


class ReplRenderer:
    def __init__(self, bus: EventBus) -> None:
        self._last_was_thinking = False
        bus.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        t = event.type
        d = event.data
        if t == EventType.AGENT_STARTED:
            self._print("hyusk is thinking...")
        elif t == EventType.AGENT_THINKING:
            # Don't spam the user; keep quiet.
            pass
        elif t == EventType.AGENT_TEXT:
            text = d.get("text", "")
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
        elif t == EventType.AGENT_TOOL_CALL:
            pass  # logged only when started
        elif t == EventType.TOOL_STARTED:
            name = d.get("name", "?")
            args = d.get("arguments", {})
            self._print()
            self._print(f"\u250C\u2500 {name}")
            for k, v in args.items():
                self._print(f"\u2502 {k}: {_short(v)}")
            self._print("\u2514" + "\u2500" * 24)
        elif t == EventType.TOOL_COMPLETED:
            err = d.get("error")
            dur = d.get("duration_ms", 0)
            if err:
                self._print(f"[error] {err}")
            else:
                self._print(f"[ok in {dur} ms]")
        elif t == EventType.AGENT_COMPLETED:
            self._print()
            iters = d.get("iterations", 0)
            self._print(f"\u2014 done ({iters} iteration{'s' if iters != 1 else ''})")
            self._print()
        elif t == EventType.AGENT_ERROR:
            self._print(f"[agent error] {d.get('error')}")

    def _print(self, s: str = "") -> None:
        sys.stdout.write(s + "\n")
        sys.stdout.flush()


def run_repl(
    *,
    agent: Agent,
    session: Session,
    session_dir: str,
    prompt: str = "hyusk > ",
    grant_callback: Callable[[str, dict], bool] | None = None,
) -> int:
    bus = agent.bus
    ReplRenderer(bus)
    print("hyusk v0.1.0  (type 'exit' or Ctrl-D to quit, 'help' for commands)")

    while True:
        try:
            user_input = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        cmd = user_input.strip()
        if not cmd:
            continue
        if cmd in ("exit", "quit", ":q"):
            break
        if cmd == "help":
            print("commands: help, exit, session, reset, tools")
            continue
        if cmd == "session":
            print(f"session id: {session.id}")
            print(f"messages: {len(session.messages)}")
            continue
        if cmd == "reset":
            session.messages = []
            print("session cleared.")
            continue
        if cmd == "tools":
            print("available tools:")
            for t in agent.registry.all():
                print(f"  - {t.name} ({t.permission})")
            continue

        try:
            result = agent.run(list(session.messages), user_input=user_input)
            session.messages = list(result.session_messages)
            session.save(session_dir)
        except AgentLoopLimit as exc:
            print(f"[error] {exc}")
        except HyuskError as exc:
            print(f"[error] {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[unexpected error] {type(exc).__name__}: {exc}")

    return 0


def _short(value, limit: int = 80) -> str:
    s = repr(value)
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return s
