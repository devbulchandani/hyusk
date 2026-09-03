"""Application wiring and CLI entry point."""

from __future__ import annotations

import argparse
import sys

from ..agent.loop import Agent
from ..config.config import Config
from ..events.events import EventBus
from ..llm.openai_compat import OpenAICompatProvider
from ..llm.provider import LLMProvider
from ..permissions.policy import PermissionPolicy
from ..sessions.session import Session
from ..tools.filesystem.tools import register_filesystem_tools
from ..tools.git.tools import register_git_tools
from ..tools.process.tools import register_process_tools
from ..tools.registry import ToolRegistry
from ..tools.shell.tools import register_shell_tools
from .repl import run_repl


def build_provider(cfg: Config) -> LLMProvider:
    if cfg.llm.provider == "openai":
        return OpenAICompatProvider(
            api_key=cfg.llm.api_key,
            base_url=cfg.llm.base_url,
            default_model=cfg.llm.model,
        )
    # Fall back: any non-openai provider still gets a default OpenAI-compat
    # transport; users can configure a custom base_url.
    return OpenAICompatProvider(
        api_key=cfg.llm.api_key,
        base_url=cfg.llm.base_url,
        default_model=cfg.llm.model,
    )


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_filesystem_tools(reg)
    register_shell_tools(reg)
    register_process_tools(reg)
    register_git_tools(reg)
    return reg


def build_policy(cfg: Config) -> PermissionPolicy:
    require = set(cfg.permissions.require_prompt)
    # By default, require prompt for destructive actions.
    require.update({"kill_process"})
    return PermissionPolicy(require_prompt=sorted(require))


def grant_callback(tool_name: str, arguments: dict) -> bool:
    """Interactive confirmation for destructive tools."""
    if not sys.stdin.isatty():
        # Non-interactive: refuse rather than silently auto-allow.
        sys.stderr.write(f"[hyusk] refusing '{tool_name}' (no TTY for confirmation)\n")
        return False
    sys.stderr.write(f"Allow hyusk to call {tool_name} with {arguments}? [y/N] ")
    sys.stderr.flush()
    try:
        ans = input()
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hyusk",
        description="Cross-platform computer agent.",
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
    args = parser.parse_args(argv)

    cfg = Config.load()
    if args.model:
        cfg.llm.model = args.model

    registry = build_registry()
    policy = build_policy(cfg)
    bus = EventBus()
    provider = build_provider(cfg)
    agent = Agent(
        llm=provider,
        registry=registry,
        policy=policy,
        bus=bus,
        model=cfg.llm.model,
        max_iterations=cfg.agent.max_iterations,
        grant_callback=None if args.no_confirm else grant_callback,
    )

    if args.list_sessions:
        for s in Session.list_sessions(cfg.session_dir):
            print(f"{s['id']}  created={s.get('created_at')}")
        return 0

    if args.session:
        try:
            session = Session.load(cfg.session_dir, args.session)
        except Exception as exc:
            print(f"[hyusk] failed to load session: {exc}", file=sys.stderr)
            return 2
    else:
        session = Session.create()

    if args.prompt:
        one_shot = " ".join(args.prompt)
        from ..events.events import EventType

        def _print_events(event):
            if event.type == EventType.AGENT_TEXT:
                sys.stdout.write(event.data.get("text", ""))
                sys.stdout.flush()
            elif event.type == EventType.TOOL_STARTED:
                sys.stderr.write(f"\n-> {event.data.get('name')}\n")
                sys.stderr.flush()
            elif event.type == EventType.TOOL_COMPLETED:
                err = event.data.get("error")
                dur = event.data.get("duration_ms", 0)
                if err:
                    sys.stderr.write(f"   error: {err}\n")
                else:
                    sys.stderr.write(f"   ok ({dur} ms)\n")
                sys.stderr.flush()
            elif event.type == EventType.AGENT_COMPLETED:
                sys.stdout.write("\n")
                sys.stdout.flush()

        bus.subscribe(_print_events)
        try:
            result = agent.run(list(session.messages), user_input=one_shot)
            session.messages = list(result.session_messages)
            session.save(cfg.session_dir)
            print(f"\n[session {session.id}]")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"[hyusk] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    return run_repl(
        agent=agent,
        session=session,
        session_dir=cfg.session_dir,
        grant_callback=None if args.no_confirm else grant_callback,
    )


if __name__ == "__main__":
    sys.exit(main())
