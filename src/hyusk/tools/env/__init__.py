"""Environment variable tool.

Allows the LLM to read (and on explicit request, set) environment
variables. Read access is safe; write access is gated by the
permission policy.
"""
from __future__ import annotations

import os
from typing import Any

from ...tools.base import READ, Tool


def env_get_tool() -> Tool:
    def execute(args: dict) -> dict:
        name = args.get("name", "")
        if not name:
            return {"error": "name is required"}
        if name in os.environ:
            return {"name": name, "value": os.environ[name]}
        return {"name": name, "value": None, "present": False}
    return Tool(
        name="env.get",
        description=(
            "Get the value of an environment variable. Returns the "
            "value as a string, or null if the variable is not set."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Env var name"},
            },
            "required": ["name"],
        },
        permission=READ,
        execute=execute,
    )


def register_env_tools(registry) -> None:
    registry.register(env_get_tool())
