"""Basic safe tools."""

import platform
import time
from datetime import datetime
from typing import Any

from hyusk.tools.base import SafeTool


class GetTimeTool(SafeTool):
    """Get current time and date."""

    @property
    def name(self) -> str:
        return "get_time"

    @property
    def description(self) -> str:
        return "Get the current date and time. Returns formatted timestamp with timezone."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Optional timezone (e.g., 'UTC', 'America/New_York')",
                },
                "format": {
                    "type": "string",
                    "description": "Optional format string (e.g., '%Y-%m-%d %H:%M:%S')",
                },
            },
            "required": [],
        }

    @property
    def category(self) -> str:
        return "system"

    async def execute(
        self, timezone: str | None = None, format: str | None = None
    ) -> dict[str, Any]:
        """Get current time."""
        now = datetime.now()

        if format:
            formatted = now.strftime(format)
        else:
            formatted = now.isoformat()

        return {
            "timestamp": formatted,
            "unix_timestamp": time.time(),
            "timezone": timezone or "local",
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day_of_week": now.strftime("%A"),
        }


class GetSystemInfoTool(SafeTool):
    """Get system information."""

    @property
    def name(self) -> str:
        return "get_system_info"

    @property
    def description(self) -> str:
        return "Get information about the current system including OS, architecture, and hostname."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    @property
    def category(self) -> str:
        return "system"

    async def execute(self) -> dict[str, Any]:
        """Get system information."""
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
        }


class EchoTool(SafeTool):
    """Echo back the input (for testing)."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the provided message. Useful for testing."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message to echo back",
                },
            },
            "required": ["message"],
        }

    @property
    def category(self) -> str:
        return "utility"

    async def execute(self, message: str) -> dict[str, Any]:
        """Echo the message."""
        return {
            "echoed": message,
            "length": len(message),
        }


class CalculatorTool(SafeTool):
    """Perform basic calculations."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "Perform basic arithmetic calculations. Supports +, -, *, /, **, sqrt, abs."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)')",
                },
            },
            "required": ["expression"],
        }

    @property
    def category(self) -> str:
        return "utility"

    async def execute(self, expression: str) -> dict[str, Any]:
        """Evaluate mathematical expression."""
        import math
        from hyusk.tools.base import ToolExecutionError

        # Whitelist of allowed operations
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
        }

        try:
            # Evaluate expression safely
            result = eval(expression, {"__builtins__": {}}, allowed_names)

            return {
                "expression": expression,
                "result": result,
                "type": type(result).__name__,
            }

        except Exception as e:
            raise ToolExecutionError(f"Failed to evaluate expression: {str(e)}")
