"""V2 CLI entry point.

Subcommands:
  hyusk [PROMPT]            # REPL (default) or one-shot if PROMPT supplied
  hyusk daemon start        # start the daemon (foreground)
  hyusk daemon stop         # stop the daemon
  hyusk daemon status       # print daemon status
  hyusk sessions            # list sessions (alias for --list-sessions)
  hyusk --help

If a daemon is running on the configured host:port, the CLI sends its work
to the daemon over WebSocket. Otherwise it falls back to an in-process
agent (V1 behavior).
"""

from __future__ import annotations

import argparse
import os
import sys

from ..agent.loop import Agent
from ..client.client import (
    daemon_reachable,
    list_sessions_sync,
    run_over_daemon_sync,
)
from ..config.config import Config
from ..daemon.registry_builder import build_policy, build_provider, build_registry
from ..daemon.server import (
    clear_pid_file,
    is_running,
    serve_forever,
)
from ..events.events import EventBus
from ..sessions.session import Session

# ---- helpers ----


def _in_process_agent(cfg: Config, *, no_confirm: bool) -> Agent:
    registry = build_registry()
    policy = build_policy(cfg)
    bus = EventBus()
    provider = build_provider(cfg)
    grant_cb = None if no_confirm else _interactive_grant
    return Agent(
        llm=provider,
        registry=registry,
        policy=policy,
        bus=bus,
        model=cfg.llm.model,
        max_iterations=cfg.agent.max_iterations,
        grant_callback=grant_cb,
    )


def _interactive_grant(tool_name: str, arguments: dict) -> bool:
    if not sys.stdin.isatty():
        sys.stderr.write(f"[hyusk] refusing '{tool_name}' (no TTY for confirmation)\n")
        return False
    sys.stderr.write(f"Allow hyusk to call {tool_name} with {arguments}? [y/N] ")
    sys.stderr.flush()
    try:
        ans = input()
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def _render_event(event_name: str, data: dict) -> None:
    if event_name == "agent.text":
        text = data.get("text", "")
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
    elif event_name == "tool.started":
        name = data.get("name", "?")
        args = data.get("arguments", {})
        sys.stderr.write(f"\n-> {name}\n")
        for k, v in args.items():
            sys.stderr.write(f"   {k}: {_short(v)}\n")
        sys.stderr.flush()
    elif event_name == "tool.completed":
        err = data.get("error")
        dur = data.get("duration_ms", 0)
        if err:
            sys.stderr.write(f"   error: {err}\n")
        else:
            sys.stderr.write(f"   ok ({dur} ms)\n")
        sys.stderr.flush()
    elif event_name == "agent.completed":
        iters = data.get("iterations", 0)
        sys.stderr.write(f"\n\u2014 done ({iters} iteration{'s' if iters != 1 else ''})\n")
        sys.stderr.flush()


def _short(value, limit: int = 80) -> str:
    s = repr(value)
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return s


# ---- one-shot path ----


def _run_one_shot(
    cfg: Config,
    *,
    prompt: str,
    session_id: str | None,
    no_confirm: bool,
    use_daemon: bool,
) -> int:
    if use_daemon:
        if not daemon_reachable(cfg.daemon.host, cfg.daemon.port):
            print(
                f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}; "
                "falling back to in-process agent",
                file=sys.stderr,
            )
            use_daemon = False
    if use_daemon:
        return _run_one_shot_via_daemon(cfg, prompt=prompt, session_id=session_id)

    agent = _in_process_agent(cfg, no_confirm=no_confirm)

    if session_id:
        try:
            session = Session.load(cfg.session_dir, session_id)
        except Exception as exc:
            print(f"[hyusk] failed to load session: {exc}", file=sys.stderr)
            return 2
    else:
        session = Session.create()

    bus = agent.bus
    bus.subscribe(lambda ev: _render_event(ev.type.value, ev.data))

    try:
        result = agent.run(list(session.messages), user_input=prompt)
        session.messages = list(result.session_messages)
        session.save(cfg.session_dir)
        print(f"\n[session {session.id}]")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[hyusk] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _run_one_shot_via_daemon(cfg: Config, *, prompt: str, session_id: str | None) -> int:
    try:
        outcome = run_over_daemon_sync(
            host=cfg.daemon.host,
            port=cfg.daemon.port,
            input_text=prompt,
            session_id=session_id,
            model=cfg.llm.model,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[hyusk] daemon error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # Replay collected events through the same renderer for consistent UI.
    for ev in outcome.events:
        _render_event(ev.event, ev.data)

    if not outcome.ok:
        print(f"[hyusk] {outcome.error}", file=sys.stderr)
        return 1
    print(f"\n[session {outcome.session_id}]")
    return 0


# ---- REPL path ----


def _run_repl(
    cfg: Config,
    *,
    session_id: str | None,
    no_confirm: bool,
    use_daemon: bool,
) -> int:
    if use_daemon and daemon_reachable(cfg.daemon.host, cfg.daemon.port):
        return _run_repl_via_daemon(cfg, session_id=session_id)
    if use_daemon:
        print(
            f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}; "
            "starting in-process agent",
            file=sys.stderr,
        )

    # In-process REPL
    from .repl import run_repl

    agent = _in_process_agent(cfg, no_confirm=no_confirm)
    if session_id:
        try:
            session = Session.load(cfg.session_dir, session_id)
        except Exception as exc:
            print(f"[hyusk] failed to load session: {exc}", file=sys.stderr)
            return 2
    else:
        session = Session.create()
    return run_repl(
        agent=agent,
        session=session,
        session_dir=cfg.session_dir,
        grant_callback=None if no_confirm else _interactive_grant,
    )


def _run_repl_via_daemon(cfg: Config, *, session_id: str | None) -> int:
    current_session = session_id
    print(f"hyusk v0.2.0  (connected to daemon at {cfg.daemon.host}:{cfg.daemon.port})")
    print("(type 'exit' or Ctrl-D to quit, 'help' for commands)")
    while True:
        try:
            user_input = input("hyusk > ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        cmd = user_input.strip()
        if not cmd:
            continue
        if cmd in ("exit", "quit", ":q"):
            break
        if cmd == "help":
            print("commands: help, exit, session, reset, tools, status, daemon")
            continue
        if cmd == "session":
            print(f"current session: {current_session or '<new>'}")
            continue
        if cmd == "reset":
            current_session = None
            print("next turn will start a new session")
            continue
        if cmd == "tools":
            print("available tools (resolved from server):")
            print("  - list_directory, read_file, write_file")
            print("  - shell.execute, list_processes, kill_process")
            print("  - git.status, git.diff, git.log, git.branch")
            continue
        if cmd == "status":
            print(f"daemon: {cfg.daemon.host}:{cfg.daemon.port} (connected)")
            continue
        if cmd == "daemon":
            print(f"daemon host:port = {cfg.daemon.host}:{cfg.daemon.port}")
            continue

        try:
            outcome = run_over_daemon_sync(
                host=cfg.daemon.host,
                port=cfg.daemon.port,
                input_text=user_input,
                session_id=current_session,
                model=cfg.llm.model,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[hyusk] daemon error: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        if not outcome.ok:
            print(f"[hyusk] {outcome.error}", file=sys.stderr)
            continue
        for ev in outcome.events:
            _render_event(ev.event, ev.data)
        current_session = outcome.session_id
        print()
    return 0


# ---- daemon subcommand ----


def _cmd_daemon(args: argparse.Namespace) -> int:
    sub = args.daemon_action
    if sub == "status":
        info = is_running()
        if info:
            cfg = Config.load()
            print(f"running (pid={info['pid']}, listening on {cfg.daemon.host}:{cfg.daemon.port})")
            return 0
        cfg = Config.load()
        print(f"not running (would listen on {cfg.daemon.host}:{cfg.daemon.port})")
        return 1
    if sub == "stop":
        info = is_running()
        if not info:
            print("daemon is not running", file=sys.stderr)
            return 0
        pid = info["pid"]
        try:
            os.kill(pid, 15)  # SIGTERM
        except OSError as exc:
            print(f"failed to signal daemon: {exc}", file=sys.stderr)
            return 1
        # wait up to ~3s for the daemon to release the pidfile
        for _ in range(30):
            if not is_running():
                clear_pid_file()
                print(f"daemon (pid={pid}) stopped")
                return 0
            import time
            time.sleep(0.1)
        print("daemon did not stop within 3s; try again or kill -9", file=sys.stderr)
        return 1
    if sub == "start":
        info = is_running()
        if info:
            print(f"daemon already running (pid={info['pid']})", file=sys.stderr)
            return 0
        serve_forever()
        return 0
    print(f"unknown daemon action: {sub}", file=sys.stderr)
    return 2


# ---- argparse ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyusk",
        description="Cross-platform computer agent (V2: with optional daemon).",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="If supplied, runs a single turn and exits. Otherwise starts an interactive REPL.",
    )
    parser.add_argument("--session", default=None, help="Resume an existing session id.")
    parser.add_argument("--list-sessions", action="store_true", help="List known sessions and exit.")
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Disable interactive confirmation for destructive tools (auto-allow).",
    )
    parser.add_argument("--model", default=None, help="Override LLM model.")
    parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="Force in-process agent even if the daemon is running.",
    )
    parser.add_argument(
        "--daemon-only",
        action="store_true",
        help="Require the daemon; fail if it is not reachable.",
    )
    parser.add_argument(
        "--daemon-action",
        choices=["start", "stop", "status"],
        default=None,
        help="Manage the local daemon (start|stop|status).",
    )
    return parser


def _normalize_argv(argv: list[str] | None) -> list[str]:
    """Translate the legacy `hyusk daemon start` syntax into `--daemon-action start`
    and `hyusk sessions` into `--list-sessions` so we can use simple flags."""
    if argv is None:
        return []
    if argv and argv[0] == "daemon" and len(argv) >= 2 and argv[1] in ("start", "stop", "status"):
        return ["--daemon-action", argv[1], *argv[2:]]
    if argv and argv[0] == "sessions":
        return ["--list-sessions", *argv[1:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    import sys as _sys
    if argv is None:
        argv = _sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(argv))
    cfg = Config.load()
    if args.model:
        cfg.llm.model = args.model

    if args.daemon_action:
        return _cmd_daemon(argparse.Namespace(daemon_action=args.daemon_action))
    if args.list_sessions:
        if daemon_reachable(cfg.daemon.host, cfg.daemon.port):
            try:
                sessions = list_sessions_sync(cfg.daemon.host, cfg.daemon.port)
                for s in sessions:
                    print(f"{s['id']}  created={s.get('created_at')}")
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"[hyusk] daemon error: {exc}", file=sys.stderr)
                # fall through to local listing
        for s in Session.list_sessions(cfg.session_dir):
            print(f"{s['id']}  created={s.get('created_at')}")
        return 0

    use_daemon = not args.no_daemon
    if args.daemon_only:
        if not daemon_reachable(cfg.daemon.host, cfg.daemon.port):
            print(
                f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}",
                file=sys.stderr,
            )
            return 1

    # `--list-sessions` is handled above; default to one-shot if a
    # prompt was supplied, otherwise start the REPL.
    if args.prompt:
        return _run_one_shot(
            cfg,
            prompt=" ".join(args.prompt),
            session_id=args.session,
            no_confirm=args.no_confirm,
            use_daemon=use_daemon,
        )

    return _run_repl(
        cfg,
        session_id=args.session,
        no_confirm=args.no_confirm,
        use_daemon=use_daemon,
    )


if __name__ == "__main__":
    sys.exit(main())
