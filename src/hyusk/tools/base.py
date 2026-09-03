"""Tool abstraction.

A Tool is a small, named capability that the agent can invoke.
Tools declare:
  - name, description
  - input schema (JSON-schema-like dict for V1 simplicity)
  - permission category
  - execute() that takes a validated dict and returns a result dict
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core.errors import InvalidInput

# Permission categories. Used by the policy to allow/deny tool calls.
READ = "READ"
WRITE = "WRITE"
EXECUTE = "EXECUTE"
DESTRUCTIVE = "DESTRUCTIVE"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    permission: str
    execute: Callable[[dict[str, Any]], dict[str, Any]]
    # Optional timeout for execute (seconds)
    timeout_s: float | None = None

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        validate(arguments, self.input_schema, tool_name=self.name)
        if self.timeout_s is not None:
            return _run_with_timeout(self.execute, arguments, self.timeout_s)
        return self.execute(arguments)


def _run_with_timeout(
    fn: Callable[[dict[str, Any]], dict[str, Any]],
    args: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """Naive timeout wrapper using a daemon thread.

    Adequate for V1 (no subprocess forking inside tools). Future PTY work
    can replace this with native cancellation.
    """
    import threading
    result: dict[str, Any] = {}
    error: dict[str, Exception] = {}

    def target() -> None:
        try:
            result["value"] = fn(args)
        except Exception as exc:  # noqa: BLE001
            error["value"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        from ..core.errors import Timeout
        raise Timeout(f"tool execution exceeded {timeout_s}s")
    if "value" in error:
        raise error["value"]
    return result.get("value", {})


# Minimal JSON-schema-ish validator. We avoid a heavy dep for V1.
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validate(arguments: dict[str, Any], schema: dict[str, Any], *, tool_name: str) -> None:
    if not isinstance(arguments, dict):
        raise InvalidInput(f"{tool_name}: arguments must be an object")
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    for key in required or []:
        if key not in arguments:
            raise InvalidInput(f"{tool_name}: missing required argument '{key}'")
    for key, val in arguments.items():
        sub = props.get(key)
        if sub is None:
            # unknown property — accept but ignore
            continue
        expected = sub.get("type") if isinstance(sub, dict) else None
        if expected and expected in _TYPE_MAP:
            py_t = _TYPE_MAP[expected]
            if not isinstance(val, py_t):
                raise InvalidInput(
                    f"{tool_name}: argument '{key}' must be {expected}, got {type(val).__name__}"
                )


@dataclass
class ToolCall:
    """A normalized tool call coming out of the LLM layer."""
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    """Structured result of a tool call."""
    name: str
    arguments: dict[str, Any]
    output: dict[str, Any]
    error: str | None = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_message(self) -> dict[str, Any]:
        if self.ok:
            return {"role": "tool", "name": self.name, "content": self.output}
        return {"role": "tool", "name": self.name, "content": {"error": self.error}}
