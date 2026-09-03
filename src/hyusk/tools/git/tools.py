"""Git tools: status, diff, log, branch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..base import READ, Tool


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run(args: list[str], cwd: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def git_status_tool() -> Tool:
    def execute(args: dict) -> dict:
        if not _git_available():
            return {"error": "git not installed"}
        cwd = args.get("cwd") or str(Path.cwd())
        rc, out, err = _run(["git", "-C", cwd, "status", "--porcelain", "--branch"], cwd=None)
        if rc != 0:
            return {"error": err.strip() or f"git status failed ({rc})"}
        return {"cwd": cwd, "raw": out}

    return Tool(
        name="git.status",
        description="Show `git status --porcelain --branch` for a directory.",
        input_schema={
            "type": "object",
            "properties": {"cwd": {"type": "string"}},
        },
        permission=READ,
        execute=execute,
    )


def git_diff_tool() -> Tool:
    def execute(args: dict) -> dict:
        if not _git_available():
            return {"error": "git not installed"}
        cwd = args.get("cwd") or str(Path.cwd())
        cmd = ["git", "-C", cwd, "diff"]
        if args.get("staged"):
            cmd.append("--staged")
        if args.get("path"):
            cmd.append("--")
            cmd.append(args["path"])
        rc, out, err = _run(cmd, cwd=None)
        if rc != 0:
            return {"error": err.strip() or f"git diff failed ({rc})"}
        cap = 50_000
        if len(out) > cap:
            out = out[:cap] + f"\n... [truncated at {cap} bytes]"
        return {"cwd": cwd, "diff": out}

    return Tool(
        name="git.diff",
        description="Show git diff. Optionally only staged changes.",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "staged": {"type": "boolean"},
                "path": {"type": "string"},
            },
        },
        permission=READ,
        execute=execute,
    )


def git_log_tool() -> Tool:
    def execute(args: dict) -> dict:
        if not _git_available():
            return {"error": "git not installed"}
        cwd = args.get("cwd") or str(Path.cwd())
        limit = int(args.get("limit", 10))
        rc, out, err = _run(
            ["git", "-C", cwd, "log", f"-n{limit}", "--pretty=format:%h %s (%an, %ad)", "--date=short"],
            cwd=None,
        )
        if rc != 0:
            return {"error": err.strip() or f"git log failed ({rc})"}
        commits = [line for line in out.splitlines() if line.strip()]
        return {"cwd": cwd, "commits": commits}

    return Tool(
        name="git.log",
        description="Show recent git commits.",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        permission=READ,
        execute=execute,
    )


def git_branch_tool() -> Tool:
    def execute(args: dict) -> dict:
        if not _git_available():
            return {"error": "git not installed"}
        cwd = args.get("cwd") or str(Path.cwd())
        rc, out, err = _run(["git", "-C", cwd, "branch", "--show-current"], cwd=None)
        if rc != 0:
            return {"error": err.strip() or f"git branch failed ({rc})"}
        return {"cwd": cwd, "branch": out.strip()}

    return Tool(
        name="git.branch",
        description="Show the current git branch.",
        input_schema={
            "type": "object",
            "properties": {"cwd": {"type": "string"}},
        },
        permission=READ,
        execute=execute,
    )


def register_git_tools(registry) -> None:
    registry.register(git_status_tool())
    registry.register(git_diff_tool())
    registry.register(git_log_tool())
    registry.register(git_branch_tool())
