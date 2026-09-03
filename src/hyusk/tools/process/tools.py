"""Process tools: list_processes, kill_process."""

from __future__ import annotations

from ...core.errors import InvalidInput
from ...platform.process import make_process_manager
from ..base import DESTRUCTIVE, READ, Tool


def list_processes_tool() -> Tool:
    def execute(args: dict) -> dict:
        sort_by = args.get("sort_by", "cpu")
        limit = int(args.get("limit", 25))
        pm = make_process_manager()
        try:
            procs = pm.list(sort_by=sort_by, limit=limit)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {"processes": [p.to_dict() for p in procs]}

    return Tool(
        name="list_processes",
        description="List running processes. Sortable by cpu|mem|pid|time.",
        input_schema={
            "type": "object",
            "properties": {
                "sort_by": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        permission=READ,
        execute=execute,
    )


def kill_process_tool() -> Tool:
    def execute(args: dict) -> dict:
        pid = args["pid"]
        if not isinstance(pid, int) or pid <= 0:
            raise InvalidInput("kill_process: 'pid' must be a positive integer")
        signal = args.get("signal", "TERM")
        pm = make_process_manager()
        try:
            pm.kill(pid, signal=str(signal))
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {"killed": pid, "signal": signal}

    return Tool(
        name="kill_process",
        description="Send a signal (TERM|KILL|INT|HUP) to a process by PID.",
        input_schema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "signal": {"type": "string"},
            },
            "required": ["pid"],
        },
        permission=DESTRUCTIVE,
        execute=execute,
    )


def register_process_tools(registry) -> None:
    registry.register(list_processes_tool())
    registry.register(kill_process_tool())
