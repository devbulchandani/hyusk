"""Tests for terminal tools."""

import asyncio
import sys

import pytest

from hyusk.tools.terminal import (
    ProcessStartTool,
    ProcessStatusTool,
    ProcessStopTool,
    TerminalExecuteTool,
)


@pytest.mark.asyncio
async def test_terminal_execute_simple_command():
    """Test executing a simple command."""
    tool = TerminalExecuteTool()

    result = await tool.execute(command="echo 'Hello, World!'")

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "Hello, World!" in result["stdout"]
    assert result["stderr"] == ""


@pytest.mark.asyncio
async def test_terminal_execute_with_error():
    """Test executing a command that fails."""
    tool = TerminalExecuteTool()

    result = await tool.execute(command="exit 1")

    assert result["success"] is False
    assert result["exit_code"] == 1


@pytest.mark.asyncio
async def test_terminal_execute_with_working_dir(tmp_path):
    """Test executing command in specific directory."""
    tool = TerminalExecuteTool()

    # Create test file in temp directory
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # List files in that directory
    result = await tool.execute(
        command="ls test.txt",
        working_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert "test.txt" in result["stdout"]


@pytest.mark.asyncio
async def test_terminal_execute_timeout():
    """Test command timeout."""
    tool = TerminalExecuteTool()

    # Command that sleeps longer than timeout
    with pytest.raises(Exception) as exc_info:
        await tool.execute(
            command="sleep 10",
            timeout=1,
        )

    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_process_start():
    """Test starting a background process."""
    tool = ProcessStartTool()

    # Start a process that sleeps
    result = await tool.execute(command="sleep 5")

    assert "process_id" in result
    assert result["status"] == "running"
    assert result["command"] == "sleep 5"

    pid = result["process_id"]

    # Stop the process
    stop_tool = ProcessStopTool()
    stop_result = await stop_tool.execute(process_id=pid)

    assert stop_result["status"] == "stopped"


@pytest.mark.asyncio
async def test_process_status():
    """Test checking process status."""
    start_tool = ProcessStartTool()
    status_tool = ProcessStatusTool()

    # Start a process
    result = await start_tool.execute(command="sleep 2")
    pid = result["process_id"]

    # Check status while running
    status = await status_tool.execute(process_id=pid)
    assert status["status"] == "running"
    assert status["return_code"] is None

    # Wait for process to complete
    await asyncio.sleep(3)

    # Check status after completion
    status = await status_tool.execute(process_id=pid)
    assert status["status"] == "completed"
    assert status["return_code"] == 0


@pytest.mark.asyncio
async def test_process_stop_graceful():
    """Test gracefully stopping a process."""
    start_tool = ProcessStartTool()
    stop_tool = ProcessStopTool()

    # Start a long-running process
    result = await start_tool.execute(command="sleep 30")
    pid = result["process_id"]

    # Stop it gracefully
    stop_result = await stop_tool.execute(process_id=pid, force=False)

    assert stop_result["status"] == "stopped"
    assert stop_result["process_id"] == pid


@pytest.mark.asyncio
async def test_process_stop_force():
    """Test force-killing a process."""
    start_tool = ProcessStartTool()
    stop_tool = ProcessStopTool()

    # Start a long-running process
    result = await start_tool.execute(command="sleep 30")
    pid = result["process_id"]

    # Force kill it
    stop_result = await stop_tool.execute(process_id=pid, force=True)

    assert stop_result["status"] == "stopped"
    assert "kill" in stop_result["method"]


@pytest.mark.asyncio
async def test_terminal_execute_python_script(tmp_path):
    """Test executing a Python script."""
    tool = TerminalExecuteTool()

    # Create Python script
    script = tmp_path / "hello.py"
    script.write_text('print("Hello from Python!")')

    # Execute it
    result = await tool.execute(
        command=f"{sys.executable} hello.py",
        working_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert "Hello from Python!" in result["stdout"]
