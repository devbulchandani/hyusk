"""V3 CLI entry point.

Subcommands:
  hyusk [PROMPT]            # one-shot (foreground)
  hyusk                     # REPL (foreground by default; supports bg: prompts)
  hyusk --daemon-action start|stop|status
  hyusk --list-sessions
  hyusk --help

REPL special commands:
  bg: <prompt>          # start a background task; return its id
  steer <id> <message>  # inject a follow-up message into a running task
  cancel <id>           # cancel a running task
  tasks                 # list active/recent tasks
  tools                 # list available tools
  session               # show the current foreground session id
  reset                 # next prompt starts a new session
  help                  # show this list
  exit | quit | :q      # leave the REPL

If a daemon is running on the configured host:port, the CLI uses it.
Otherwise it falls back to a local in-process agent (one task at a time,
no real concurrency, but the same UX).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from ..agent.loop import Agent
from ..agent.tasks import Task, TaskManager
from ..client.client import (
    DaemonClient,
    EventMessage,
    PendingAsk,
    TaskDone,
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
from ..sessions.store import SessionStore

# ---------- helpers ----------


def _in_process_agent(cfg: Config, *, no_confirm: bool) -> Agent:
    registry = build_registry(load_user_plugins=True)
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


def _render_event(event_name: str, data: dict, *, task_id: str | None = None) -> None:
    prefix = f"[{task_id[:8]}] " if task_id else ""
    if event_name == "agent.text":
        text = data.get("text", "")
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
    elif event_name == "tool.started":
        name = data.get("name", "?")
        args = data.get("arguments", {})
        sys.stderr.write(f"\n{prefix}-> {name}\n")
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
        cancelled = data.get("cancelled", False)
        marker = " (cancelled)" if cancelled else ""
        sys.stderr.write(f"\n{prefix}\u2014 done ({iters} iteration{'s' if iters != 1 else ''}){marker}\n")
        sys.stderr.flush()


def _short(value, limit: int = 80) -> str:
    s = repr(value)
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return s


# ---------- one-shot path ----------


def _run_one_shot(
    cfg: Config,
    *,
    prompt: str,
    session_id: str | None,
    no_confirm: bool,
    use_daemon: bool,
) -> int:
    if use_daemon and not daemon_reachable(cfg.daemon.host, cfg.daemon.port):
        print(
            f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}; "
            "falling back to in-process agent",
            file=sys.stderr,
        )
        use_daemon = False

    if use_daemon:
        return _run_one_shot_via_daemon(cfg, prompt=prompt, session_id=session_id)

    store = SessionStore(base_dir=cfg.session_dir)
    if session_id:
        try:
            session = store.load(session_id)
        except Exception as exc:
            print(f"[hyusk] failed to load session: {exc}", file=sys.stderr)
            return 2
    else:
        session = store.new()
    tm = _build_local_task_manager(cfg, no_confirm=no_confirm)
    task = tm.submit(input_text=prompt, session=session)
    info = task.result(timeout=600.0)
    for ev in _collect_events_synchronously(task):
        _render_event(ev.event, ev.data)
    if info is None:
        print("[hyusk] task timed out", file=sys.stderr)
        return 1
    if info.error:
        print(f"[hyusk] {info.error}", file=sys.stderr)
        return 1
    print(f"\n[session {session.id}  task {info.id[:8]}]")
    return 0


def _collect_events_synchronously(task: Task) -> list[EventMessage]:
    """Drain a finished task's events from its bus."""
    out: list[EventMessage] = []
    q, _ = task.events()
    while True:
        try:
            ev = q.get_nowait()
        except Exception:
            break
        if ev is None:
            break
        out.append(EventMessage(task_id=task.id, event=ev.type.value, data=ev.data))
    return out


def _build_local_task_manager(cfg: Config, *, no_confirm: bool) -> TaskManager:
    return TaskManager(
        cfg=cfg,
        llm=build_provider(cfg),
        registry=build_registry(),
        policy=build_policy(cfg),
        session_dir=cfg.session_dir,
        grant_callback=None if no_confirm else _interactive_grant,
    )


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
    for ev in outcome.events:
        _render_event(ev.event, ev.data, task_id=ev.task_id)
    if not outcome.ok:
        print(f"[hyusk] {outcome.error or 'cancelled'}", file=sys.stderr)
        return 1
    print(f"\n[session {outcome.session_id}  task {outcome.task_id[:8] if outcome.task_id else '?'}]")
    return 0


# ---------- REPL ----------


def _run_repl(
    cfg: Config,
    *,
    session_id: str | None,
    no_confirm: bool,
    use_daemon: bool,
) -> int:
    if use_daemon and daemon_reachable(cfg.daemon.host, cfg.daemon.port):
        return _run_repl_via_daemon(cfg, session_id=session_id, no_confirm=no_confirm)
    if use_daemon:
        print(
            f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}; "
            "starting in-process agent",
            file=sys.stderr,
        )
    return _run_repl_inprocess(cfg, session_id=session_id, no_confirm=no_confirm)


def _run_repl_inprocess(cfg: Config, *, session_id: str | None, no_confirm: bool) -> int:
    print("hyusk v0.3.0  (in-process agent; one task at a time)")
    print("(type 'help' for commands)")
    store = SessionStore(base_dir=cfg.session_dir)
    if session_id:
        try:
            session = store.load(session_id)
        except Exception as exc:
            print(f"[hyusk] failed to load session: {exc}", file=sys.stderr)
            return 2
    else:
        session = store.new()
    tm = _build_local_task_manager(cfg, no_confirm=no_confirm)
    current_session_id = session.id
    tasks: dict[str, Task] = {}

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
            for t in tasks.values():
                t.cancel()
            break
        if cmd == "help":
            _print_help()
            continue
        if cmd == "session":
            print(f"current session: {current_session_id}")
            continue
        if cmd == "reset":
            current_session_id = store.new().id
            print("next prompt will start a new session")
            continue
        if cmd == "tools":
            for tool in build_registry().all():
                print(f"  - {tool.name} ({tool.permission})")
            continue
        if cmd == "tasks":
            for ti in tm.list():
                print(f"  {ti.id[:8]}  {ti.state.value:9s}  iter={ti.iterations:2d}  {ti.input[:60]!r}")
            continue
        if cmd.startswith("cancel "):
            tid = cmd[7:].strip()
            ok = tm.cancel(tid)
            print(f"cancel: {tid} ok={ok}")
            continue
        if cmd.startswith("steer "):
            parts = cmd.split(None, 2)
            if len(parts) < 3:
                print("usage: steer <id> <message>")
                continue
            _, tid, msg = parts
            ok = tm.steer(tid, msg)
            print(f"steer: {tid} ok={ok}")
            continue

        # Submit a new task in the foreground (in-process: blocks until done).
        try:
            sess = store.load(current_session_id)
        except Exception:
            sess = store.new()
            current_session_id = sess.id
        task = tm.submit(input_text=cmd, session=sess)
        tasks[task.id] = task
        info = task.result(timeout=600.0)
        for ev in _collect_events_synchronously(task):
            _render_event(ev.event, ev.data, task_id=task.id)
        if info and info.error:
            print(f"[hyusk] {info.error}", file=sys.stderr)
    return 0


def _run_repl_via_daemon(cfg: Config, *, session_id: str | None, no_confirm: bool) -> int:
    print(f"hyusk v0.3.0  (connected to daemon at {cfg.daemon.host}:{cfg.daemon.port})")
    print("(type 'help' for commands)")

    async def main() -> int:
        client = DaemonClient(cfg.daemon.host, cfg.daemon.port)
        await client.connect()
        # Render every event we get. We tag it with the task id.
        client.on_event(lambda ev: _render_event(ev.event, ev.data, task_id=ev.task_id))
        client.on_done(lambda d: _print_done_summary(d))
        client.on_ask(lambda ask: _ask_prompt(ask))
        client.on_error(lambda err: print(f"[hyusk] {err}", file=sys.stderr))
        try:
            current_session_id = session_id
            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("hyusk > ")
                    )
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                cmd = user_input.strip()
                if not cmd:
                    continue
                if cmd in ("exit", "quit", ":q"):
                    break
                if cmd == "help":
                    _print_help()
                    continue
                if cmd == "session":
                    print(f"current session: {current_session_id or '<new>'}")
                    continue
                if cmd == "reset":
                    current_session_id = None
                    print("next prompt will start a new session")
                    continue
                if cmd == "tools":
                    for tool in build_registry().all():
                        print(f"  - {tool.name} ({tool.permission})")
                    continue
                if cmd == "tasks":
                    ts = await client.list_tasks()
                    if not ts:
                        print("(no active tasks)")
                    for ti in ts:
                        print(
                            f"  {ti['id'][:8]}  {ti['state']:9s}  iter={ti.get('iterations', 0):2d}  "
                            f"{ti.get('input', '')[:60]!r}"
                        )
                    continue
                if cmd.startswith("cancel "):
                    tid = cmd[7:].strip()
                    await client.cancel(tid)
                    continue
                if cmd.startswith("steer "):
                    parts = cmd.split(None, 2)
                    if len(parts) < 3:
                        print("usage: steer <id> <message>")
                        continue
                    _, tid, msg = parts
                    await client.steer(tid, msg)
                    continue
                if cmd.startswith("bg: "):
                    # Background task.
                    bg_text = cmd[4:].strip()
                    task = await client.submit(input_text=bg_text, session_id=current_session_id)
                    current_session_id = task.session_id
                    print(f"  started task {task.id[:8]} (session {task.session_id[:8]})")
                    continue

                # Foreground: submit and wait.
                task = await client.submit(input_text=cmd, session_id=current_session_id)
                current_session_id = task.session_id
                done = await client.wait_done(task.id, timeout=600.0)
                _print_done_summary(done)
        finally:
            await client.close()
        return 0

    return asyncio.run(main())


def _print_done_summary(d: TaskDone) -> None:
    marker = " (cancelled)" if d.cancelled else ""
    err = f" error={d.error}" if d.error else ""
    print(f"\n[{d.task_id[:8]}] state={d.state} iters={d.iterations}{marker}{err}")


def _ask_prompt(ask: PendingAsk) -> bool:
    if not sys.stdin.isatty():
        sys.stderr.write(f"[hyusk] refusing '{ask.tool}' (no TTY for confirmation)\n")
        return False
    sys.stderr.write(f"[{ask.task_id[:8]}] Allow {ask.tool}? args={ask.arguments} [y/N] ")
    sys.stderr.flush()
    try:
        ans = input()
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def _print_help() -> None:
    print(
        "commands:\n"
        "  bg: <prompt>            start a background task\n"
        "  steer <id> <message>    inject a follow-up message into a running task\n"
        "  cancel <id>             cancel a running task\n"
        "  tasks                   list tasks (active + recent)\n"
        "  session                 show the current session id\n"
        "  reset                   next prompt starts a new session\n"
        "  tools                   list available tools\n"
        "  help                    show this list\n"
        "  exit | quit | :q        leave the REPL\n"
    )


# ---------- daemon subcommand ----------


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
            os.kill(pid, 15)
        except OSError as exc:
            print(f"failed to signal daemon: {exc}", file=sys.stderr)
            return 1
        for _ in range(30):
            if not is_running():
                clear_pid_file()
                print(f"daemon (pid={pid}) stopped")
                return 0
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


# ---------- argparse ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyusk",
        description="Cross-platform computer agent (V5: Kokoro TTS, whisper.cpp STT, persistent tasks, daemon).",
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
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Run a voice/text client against the daemon.",
    )
    parser.add_argument(
        "--voice-action",
        choices=["setup", "doctor", "test"],
        default=None,
        help="(voice subcommand) run voice setup, doctor, or test.",
    )
    parser.add_argument("--text", action="store_true", help="(voice) Read input from stdin.")
    parser.add_argument("--mic", action="store_true", help="(voice) Capture from microphone.")
    parser.add_argument("--host", default=None, help="(voice) Daemon host.")
    parser.add_argument("--port", type=int, default=None, help="(voice) Daemon port.")
    parser.add_argument("--no-tts", action="store_true", help="(voice) Do not use TTS.")
    parser.add_argument(
        "--tts-backend",
        choices=["say", "kokoro", "openai", "none"],
        default=None,
        help="(voice) TTS backend for this run.",
    )
    parser.add_argument(
        "--tts-voice",
        default=None,
        help="(voice) TTS voice for this run.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override LLM provider for this run (openai, anthropic).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override LLM API key for this run (not saved).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override LLM base URL (for OpenAI-compatible endpoints like OpenRouter).",
    )
    parser.add_argument(
        "--config-action",
        choices=["show", "path", "set", "unset"],
        default=None,
        help="Manage the persistent config (show|path|set|unset).",
    )
    parser.add_argument(
        "--config-key",
        default=None,
        help="(config) dotted key, e.g. llm.api_key.",
    )
    parser.add_argument(
        "--config-value",
        default=None,
        help="(config) value to set.",
    )
    return parser


def _normalize_argv(argv: list[str] | None) -> list[str]:
    """Translate legacy subcommand syntax into flag form.

    Examples:
      hyusk daemon start        -> --daemon-action start
      hyusk sessions            -> --list-sessions
      hyusk config show         -> --config-action show
      hyusk config set X Y      -> --config-action set --config-key X --config-value Y
      hyusk config unset X      -> --config-action unset --config-key X
      hyusk voice --text        -> --voice --text (the rest is passed through)
    """
    if argv is None:
        return []
    if not argv:
        return argv
    if argv[0] == "daemon" and len(argv) >= 2 and argv[1] in ("start", "stop", "status"):
        return ["--daemon-action", argv[1], *argv[2:]]
    if argv[0] == "sessions":
        return ["--list-sessions", *argv[1:]]
    if argv[0] == "config" and len(argv) >= 2 and argv[1] in ("show", "path", "set", "unset"):
        action = argv[1]
        rest = argv[2:]
        if action == "set" and len(rest) >= 2:
            return [
                "--config-action", "set",
                "--config-key", rest[0],
                "--config-value", rest[1],
                *rest[2:],
            ]
        if action == "unset" and len(rest) >= 1:
            return ["--config-action", "unset", "--config-key", rest[0], *rest[1:]]
        return ["--config-action", action, *rest]
    if argv[0] == "voice" and len(argv) >= 2 and argv[1] in ("setup", "doctor", "test"):
        return ["--voice-action", argv[1], *argv[2:]]
    if argv[0] == "voice":
        return ["--voice"]
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
    # If --api-key was provided AND the config didn't already set one, use it.
    if args.api_key and not cfg.llm.api_key:
        cfg.llm.api_key = args.api_key
    if args.provider and cfg.llm.provider == "openai" and not os.environ.get("HYUSK_LLM_PROVIDER"):
        cfg.llm.provider = args.provider
    if args.base_url:
        cfg.llm.base_url = args.base_url

    # Apply per-invocation overrides for API key / provider / base URL.
    if args.api_key:
        os.environ["HYUSK_LLM_API_KEY"] = args.api_key
    if args.provider:
        os.environ["HYUSK_LLM_PROVIDER"] = args.provider
    if args.base_url:
        os.environ["HYUSK_LLM_BASE_URL"] = args.base_url

    # Handle config subcommand early.
    if args.config_action:
        from ..config.commands import path as _cfg_path
        from ..config.commands import set_value, show, unset_value
        action = args.config_action
        if action == "show":
            return show()
        if action == "path":
            return _cfg_path()
        if action == "set":
            if not args.config_key or args.config_value is None:
                print("config set requires --config-key and --config-value", file=sys.stderr)
                return 2
            return set_value(args.config_key, args.config_value)
        if action == "unset":
            if not args.config_key:
                print("config unset requires --config-key", file=sys.stderr)
                return 2
            return unset_value(args.config_key)
        print(f"unknown config action: {action}", file=sys.stderr)
        return 2

    if args.voice_action:
        from ..voice import setup as _voice_setup
        if args.voice_action == "setup":
            return _voice_setup.setup()
        if args.voice_action == "doctor":
            return _voice_setup.doctor()
        if args.voice_action == "test":
            from ..voice import tts as _voice_tts
            from ..config.config import user_config_dir
            import tomllib
            cfg = _voice_tts.TTSConfig()
            try:
                p = user_config_dir() / "config.toml"
                if p.exists():
                    with p.open("rb") as f:
                        data = tomllib.load(f).get("voice", {})
                    cfg.backend = data.get("tts_backend", "")
                    cfg.voice = data.get("tts_voice", "")
            except Exception:
                pass
            backend = _voice_tts.select_backend(cfg)
            print(f"Testing TTS backend: {backend.name()}")
            backend.speak("Hello, this is a test of the Hyusk voice stack.")
            print("Done.")
            return 0
    if args.voice:
        from ..voice.client import main as _voice_main
        voice_args: list[str] = []
        if args.text:
            voice_args.append("--text")
        if args.mic:
            voice_args.append("--mic")
        if args.model:
            voice_args.extend(["--model", args.model])
        if args.host:
            voice_args.extend(["--host", args.host])
        if args.port:
            voice_args.extend(["--port", str(args.port)])
        if args.no_tts:
            voice_args.append("--no-tts")
        if args.tts_backend:
            voice_args.extend(["--tts-backend", args.tts_backend])
        if args.tts_voice:
            voice_args.extend(["--tts-voice", args.tts_voice])
        if hasattr(args, "stt_backend") and args.stt_backend:
            voice_args.extend(["--stt-backend", args.stt_backend])
        return _voice_main(voice_args)

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
        for s in Session.list_sessions(cfg.session_dir):
            print(f"{s['id']}  created={s.get('created_at')}")
        return 0

    use_daemon = not args.no_daemon
    if args.daemon_only and not daemon_reachable(cfg.daemon.host, cfg.daemon.port):
        print(
            f"[hyusk] daemon not reachable on {cfg.daemon.host}:{cfg.daemon.port}",
            file=sys.stderr,
        )
        return 1

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
