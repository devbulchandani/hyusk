"""Typed error hierarchy for Hyusk.

Tools, agents, and the CLI translate these into friendly messages.
Never silently swallow exceptions — raise or re-raise these.
"""

from __future__ import annotations


class HyuskError(Exception):
    """Base class for all Hyusk-specific errors."""


class ToolNotFound(HyuskError):
    """Raised when a requested tool is not registered."""


class PermissionDenied(HyuskError):
    """Raised when the permission policy refuses a tool call."""

    def __init__(self, tool: str, reason: str = "") -> None:
        super().__init__(f"permission denied for tool '{tool}'{(': ' + reason) if reason else ''}")
        self.tool = tool
        self.reason = reason


class CommandFailed(HyuskError):
    """Raised when a shell command exits non-zero."""

    def __init__(self, command: str, exit_code: int, stderr: str = "") -> None:
        msg = f"command failed (exit {exit_code}): {command}"
        super().__init__(msg)
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


class Timeout(HyuskError):
    """Raised when an operation exceeds its timeout."""


class UnsupportedPlatform(HyuskError):
    """Raised when an operation is not available on the current OS."""


class FileNotFound(HyuskError):
    """Raised when a filesystem operation targets a missing path."""


class InvalidInput(HyuskError):
    """Raised when tool input fails validation."""


class ProviderError(HyuskError):
    """Raised when an LLM provider returns an unrecoverable error."""


class AgentLoopLimit(HyuskError):
    """Raised when the agent exceeds its configured iteration cap."""
