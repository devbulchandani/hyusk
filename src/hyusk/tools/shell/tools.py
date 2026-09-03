"""Shell tool."""

from __future__ import annotations

from ...platform.shell import Shell, ShellResult, make_shell
from ..base import EXECUTE, Tool

_SHELL: Shell | None = None


def _get_shell() -> Shell:
    global _SHELL
    if _SHELL is None:
        _SHELL = make_shell()
    return _SHELL


def shell_execute_tool() -> Tool:
    def execute(args: dict) -> dict:
        command = args["command"]
        cwd = args.get("cwd")
        timeout = args.get("timeout", 60.0)
        try:
            result: ShellResult = _get_shell().run(
                command,
                cwd=cwd,
                timeout=float(timeout) if timeout is not None else 60.0,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        out = result.to_dict()
        # Cap stdout/stderr to a sensible size to avoid blowing up context.
        cap = 50_000
        for k in ("stdout", "stderr"):
            if len(out[k]) > cap:
                out[k] = out[k][:cap] + f"\n... [truncated at {cap} bytes]"
        return out

    return Tool(
        name="shell.execute",
        description="Run a shell command. Returns exit_code, stdout, stderr, duration_ms.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["command"],
        },
        permission=EXECUTE,
        execute=execute,
        timeout_s=120.0,
    )


def register_shell_tools(registry) -> None:
    registry.register(shell_execute_tool())
