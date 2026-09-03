"""OS-aware process listing / control.

V1 implements macOS and Linux via standard `ps`/proc; Windows returns
`UnsupportedPlatform` for operations that genuinely cannot work there.

The interface lives here; per-platform details live in submodules.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from ..core.errors import CommandFailed, UnsupportedPlatform


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    user: str
    command: str
    cpu: float = 0.0
    mem: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "user": self.user,
            "command": self.command,
            "cpu": self.cpu,
            "mem": self.mem,
        }


class ProcessManager:
    """Base interface. Subclasses fill in platform-specific implementations."""

    def list(self, sort_by: str = "cpu", limit: int = 50) -> list[ProcessInfo]:
        raise UnsupportedPlatform("process listing not implemented on this platform")

    def kill(self, pid: int, signal: str = "TERM") -> None:
        raise UnsupportedPlatform("process kill not implemented on this platform")


class PosixProcessManager(ProcessManager):
    """Uses ps(1) for cross-Unix support (macOS, Linux)."""

    def list(self, sort_by: str = "cpu", limit: int = 50) -> list[ProcessInfo]:
        if not shutil.which("ps"):
            raise UnsupportedPlatform("`ps` not available on this platform")
        # Validate sort key (future enhancement: pass to ps).
        _sort_keys = {"cpu", "mem", "pid", "time"}
        if sort_by not in _sort_keys:
            sort_by = "cpu"
        # -axo: all processes, all users, custom format
        ps_cmd = (
            "ps -axo pid=,ppid=,user=,%cpu=,%mem=,comm=,args= "
            f"| sort -nr | head -n {int(limit)}"
        )
        proc = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CommandFailed("ps", proc.returncode, proc.stderr)
        out: list[ProcessInfo] = []
        for line in (proc.stdout or "").splitlines():
            parts = line.strip().split(None, 5)
            if len(parts) < 6:
                continue
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
                cpu = float(parts[3])
                mem = float(parts[4])
            except ValueError:
                continue
            user = parts[2]
            command = parts[5]
            out.append(ProcessInfo(pid=pid, ppid=ppid, user=user, cpu=cpu, mem=mem, command=command))
        return out

    def kill(self, pid: int, signal: str = "TERM") -> None:
        sig = signal.upper()
        if sig not in {"TERM", "KILL", "INT", "HUP"}:
            raise UnsupportedPlatform(f"unsupported signal: {signal}")
        if sig == "KILL":
            cmd = f"kill -9 {int(pid)}"
        else:
            cmd = f"kill -s {sig} {int(pid)}"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CommandFailed(cmd, proc.returncode, proc.stderr)


class WindowsProcessManager(ProcessManager):
    """Windows: not fully implemented in V1, returns structured unsupported errors."""

    def list(self, sort_by: str = "cpu", limit: int = 50) -> list[ProcessInfo]:
        raise UnsupportedPlatform("process listing on Windows is not implemented in V1")

    def kill(self, pid: int, signal: str = "TERM") -> None:
        raise UnsupportedPlatform("process kill on Windows is not implemented in V1")


def make_process_manager() -> ProcessManager:
    if sys.platform == "win32":
        return WindowsProcessManager()
    return PosixProcessManager()
