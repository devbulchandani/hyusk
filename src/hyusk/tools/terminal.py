"""Terminal execution tools."""

import asyncio
import os
import shlex
import signal
from pathlib import Path
from typing import Any

from hyusk.logging import get_logger
from hyusk.models import PermissionLevel
from hyusk.tools.base import SensitiveTool, Tool, ToolError

logger = get_logger(__name__)


class TerminalExecuteTool(SensitiveTool):
    """Execute a shell command and return output."""

    name = "terminal_execute"
    description = "Execute a shell command and capture its output. Use for one-off commands."
    category = "terminal"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for command (defaults to current directory)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute a shell command.

        Args:
            command: Command to execute
            working_dir: Working directory
            timeout: Timeout in seconds

        Returns:
            Dictionary with stdout, stderr, exit_code
        """
        logger.info(f"Executing command", command=command, working_dir=working_dir)

        # Validate and normalize working directory
        if working_dir:
            work_path = Path(working_dir).expanduser().resolve()
            if not work_path.exists():
                raise ToolError(f"Working directory does not exist: {working_dir}")
            if not work_path.is_dir():
                raise ToolError(f"Working directory is not a directory: {working_dir}")
            cwd = str(work_path)
        else:
            cwd = os.getcwd()

        # Security: Log command for audit
        logger.info("Terminal command requested", command=command, cwd=cwd)

        try:
            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # Kill process on timeout
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                raise ToolError(f"Command timed out after {timeout} seconds")

            exit_code = process.returncode

            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

            logger.info(
                "Command completed",
                exit_code=exit_code,
                stdout_length=len(stdout_str),
                stderr_length=len(stderr_str),
            )

            return {
                "stdout": stdout_str,
                "stderr": stderr_str,
                "exit_code": exit_code,
                "success": exit_code == 0,
            }

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise ToolError(f"Command execution failed: {str(e)}")


class ProcessStartTool(SensitiveTool):
    """Start a background process."""

    name = "process_start"
    description = "Start a long-running process in the background. Returns process ID."
    category = "terminal"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to start",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (defaults to current directory)",
                },
            },
            "required": ["command"],
        }

    # Track running processes
    _processes: dict[int, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Start a background process.

        Args:
            command: Command to start
            working_dir: Working directory

        Returns:
            Dictionary with process_id and status
        """
        logger.info(f"Starting process", command=command)

        # Validate working directory
        if working_dir:
            work_path = Path(working_dir).expanduser().resolve()
            if not work_path.exists():
                raise ToolError(f"Working directory does not exist: {working_dir}")
            cwd = str(work_path)
        else:
            cwd = os.getcwd()

        try:
            # Start process
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            pid = process.pid
            self._processes[pid] = process

            logger.info(f"Process started", pid=pid, command=command)

            return {
                "process_id": pid,
                "status": "running",
                "command": command,
            }

        except Exception as e:
            logger.error(f"Failed to start process: {e}")
            raise ToolError(f"Failed to start process: {str(e)}")


class ProcessStatusTool(Tool):
    """Check status of a background process."""

    name = "process_status"
    description = "Check if a process is running and get its status"
    category = "terminal"
    permission_level = PermissionLevel.SAFE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "integer",
                    "description": "Process ID to check",
                },
            },
            "required": ["process_id"],
        }

    async def execute(self, process_id: int) -> dict[str, Any]:
        """Check process status.

        Args:
            process_id: Process ID

        Returns:
            Dictionary with status information
        """
        process = ProcessStartTool._processes.get(process_id)

        if not process:
            return {
                "process_id": process_id,
                "status": "unknown",
                "message": "Process not found in tracking",
            }

        return_code = process.returncode

        if return_code is None:
            # Still running
            return {
                "process_id": process_id,
                "status": "running",
                "return_code": None,
            }
        else:
            # Completed
            return {
                "process_id": process_id,
                "status": "completed",
                "return_code": return_code,
            }


class ProcessStopTool(SensitiveTool):
    """Stop a background process."""

    name = "process_stop"
    description = "Stop a running background process"
    category = "terminal"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "integer",
                    "description": "Process ID to stop",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force kill if true, graceful terminate if false",
                },
            },
            "required": ["process_id"],
        }

    async def execute(self, process_id: int, force: bool = False) -> dict[str, Any]:
        """Stop a process.

        Args:
            process_id: Process ID
            force: Whether to force kill

        Returns:
            Dictionary with result
        """
        process = ProcessStartTool._processes.get(process_id)

        if not process:
            raise ToolError(f"Process {process_id} not found")

        if process.returncode is not None:
            return {
                "process_id": process_id,
                "status": "already_stopped",
                "return_code": process.returncode,
            }

        try:
            if force:
                process.kill()
                method = "killed"
            else:
                process.terminate()
                method = "terminated"

            # Wait a bit for process to stop
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                if not force:
                    # Try force kill
                    process.kill()
                    await process.wait()
                    method = "force_killed"

            # Remove from tracking
            del ProcessStartTool._processes[process_id]

            logger.info(f"Process stopped", pid=process_id, method=method)

            return {
                "process_id": process_id,
                "status": "stopped",
                "method": method,
                "return_code": process.returncode,
            }

        except Exception as e:
            logger.error(f"Failed to stop process: {e}")
            raise ToolError(f"Failed to stop process: {str(e)}")
