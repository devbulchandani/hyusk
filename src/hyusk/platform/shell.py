"""OS-independent shell abstraction.

V1 only needs a one-shot command executor that captures stdout, stderr,
exit code, and timing. The interface is intentionally small so a future
PTY-backed persistent terminal can slot in without changing callers.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Timeout, UnsupportedPlatform


@dataclass
class ShellResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
        }


class Shell:
    """Run commands. Stateless for V1; persistent terminals later."""

    def run(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = 60.0,
        max_output_bytes: int | None = None,
    ) -> ShellResult:
        work_dir = str(cwd) if cwd is not None else os.getcwd()
        merged_env: dict[str, str] = dict(os.environ)
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        start = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise Timeout(f"command timed out after {timeout}s: {command}") from exc
        except FileNotFoundError as exc:
            # happens when the shell itself cannot start (e.g. /bin/sh missing)
            raise UnsupportedPlatform(f"shell unavailable: {exc}") from exc
        duration_ms = int((time.time() - start) * 1000)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if max_output_bytes is not None:
            stdout = _truncate(stdout, max_output_bytes)
            stderr = _truncate(stderr, max_output_bytes)
        return ShellResult(
            command=command,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    def quote(self, value: str) -> str:
        """Safely quote a value for inclusion in a shell command."""
        return shlex.quote(value)


def _truncate(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    encoded = text.encode("utf-8")[:limit]
    return encoded.decode("utf-8", errors="replace") + "\n... [truncated]"


def make_shell() -> Shell:
    """Factory. Future versions can pick a PTY-backed shell here."""
    return Shell()


def resolve_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()
