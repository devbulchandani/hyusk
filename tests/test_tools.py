"""Tests for tool system."""

import pytest
from pathlib import Path
import tempfile

from hyusk.models import PermissionLevel, ToolCall, ToolResultStatus
from hyusk.tools.base import Tool, ToolValidationError
from hyusk.tools.basic import CalculatorTool, EchoTool, GetSystemInfoTool, GetTimeTool
from hyusk.tools.filesystem import FileExistsTool, ListDirectoryTool, ReadFileTool, WriteFileTool
from hyusk.tools.registry import ToolRegistry


def test_tool_registry_register():
    """Test registering tools."""
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get_tool_count() == 1
    assert registry.get("echo") is not None


def test_tool_registry_duplicate():
    """Test registering duplicate tool raises error."""
    registry = ToolRegistry()
    tool1 = EchoTool()
    tool2 = EchoTool()

    registry.register(tool1)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool2)


def test_tool_registry_unregister():
    """Test unregistering tools."""
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)
    assert registry.get_tool_count() == 1

    registry.unregister("echo")
    assert registry.get_tool_count() == 0
    assert registry.get("echo") is None


def test_tool_registry_list():
    """Test listing tools."""
    registry = ToolRegistry()

    registry.register(EchoTool())
    registry.register(GetTimeTool())
    registry.register(CalculatorTool())

    tools = registry.list_tools()
    assert len(tools) == 3

    # Filter by category
    utility_tools = registry.list_tools(category="utility")
    assert len(utility_tools) == 2

    system_tools = registry.list_tools(category="system")
    assert len(system_tools) == 1


@pytest.mark.asyncio
async def test_echo_tool():
    """Test echo tool execution."""
    tool = EchoTool()
    result = await tool.execute(message="Hello, World!")

    assert result["echoed"] == "Hello, World!"
    assert result["length"] == 13


@pytest.mark.asyncio
async def test_get_time_tool():
    """Test get_time tool execution."""
    tool = GetTimeTool()
    result = await tool.execute()

    assert "timestamp" in result
    assert "date" in result
    assert "time" in result
    assert "day_of_week" in result


@pytest.mark.asyncio
async def test_get_system_info_tool():
    """Test system info tool execution."""
    tool = GetSystemInfoTool()
    result = await tool.execute()

    assert "platform" in result
    assert "architecture" in result
    assert "hostname" in result
    assert "python_version" in result


@pytest.mark.asyncio
async def test_calculator_tool():
    """Test calculator tool execution."""
    tool = CalculatorTool()

    # Basic arithmetic
    result = await tool.execute(expression="2 + 2")
    assert result["result"] == 4

    # Using functions
    result = await tool.execute(expression="sqrt(16)")
    assert result["result"] == 4.0

    # Complex expression
    result = await tool.execute(expression="(10 + 5) * 2")
    assert result["result"] == 30


@pytest.mark.asyncio
async def test_calculator_tool_error():
    """Test calculator tool with invalid expression."""
    tool = CalculatorTool()

    with pytest.raises(Exception):  # ToolExecutionError
        await tool.execute(expression="import os")


@pytest.mark.asyncio
async def test_read_file_tool():
    """Test reading a file."""
    tool = ReadFileTool()

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("Hello, Hyusk!")
        temp_path = f.name

    try:
        result = await tool.execute(path=temp_path)

        assert result["content"] == "Hello, Hyusk!"
        assert result["lines"] == 1
        assert result["size_bytes"] > 0
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_list_directory_tool():
    """Test listing directory contents."""
    tool = ListDirectoryTool()

    # Use temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create some test files
        (Path(temp_dir) / "file1.txt").touch()
        (Path(temp_dir) / "file2.txt").touch()
        (Path(temp_dir) / "subdir").mkdir()

        result = await tool.execute(path=temp_dir)

        assert result["count"] == 3
        assert len(result["entries"]) == 3

        # Check entries
        names = {e["name"] for e in result["entries"]}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names


@pytest.mark.asyncio
async def test_file_exists_tool():
    """Test checking if file exists."""
    tool = FileExistsTool()

    # Test existing file
    with tempfile.NamedTemporaryFile() as f:
        result = await tool.execute(path=f.name)
        assert result["exists"] is True
        assert result["type"] == "file"

    # Test non-existing file
    result = await tool.execute(path="/nonexistent/path/file.txt")
    assert result["exists"] is False


@pytest.mark.asyncio
async def test_write_file_tool():
    """Test writing to a file."""
    tool = WriteFileTool()

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "test.txt"

        result = await tool.execute(
            path=str(file_path),
            content="Test content\nLine 2"
        )

        assert result["lines_written"] == 2
        assert file_path.exists()
        assert file_path.read_text() == "Test content\nLine 2"


@pytest.mark.asyncio
async def test_tool_registry_execute():
    """Test executing tool through registry."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    tool_call = ToolCall(
        tool_name="echo",
        arguments={"message": "Test"},
    )

    result = await registry.execute_tool(tool_call)

    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["echoed"] == "Test"


@pytest.mark.asyncio
async def test_tool_registry_execute_not_found():
    """Test executing non-existent tool."""
    registry = ToolRegistry()

    tool_call = ToolCall(
        tool_name="nonexistent",
        arguments={},
    )

    result = await registry.execute_tool(tool_call)

    assert result.status == ToolResultStatus.ERROR
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_tool_registry_execute_validation_error():
    """Test executing tool with invalid arguments."""
    registry = ToolRegistry()
    registry.register(EchoTool())

    tool_call = ToolCall(
        tool_name="echo",
        arguments={},  # Missing required 'message'
    )

    result = await registry.execute_tool(tool_call)

    assert result.status == ToolResultStatus.ERROR
    assert "message" in result.error.lower()


def test_tool_schemas():
    """Test getting tool schemas."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(GetTimeTool())

    schemas = registry.get_tool_schemas()

    assert len(schemas) == 2
    assert all("name" in s for s in schemas)
    assert all("description" in s for s in schemas)
    assert all("input_schema" in s for s in schemas)


def test_tool_permission_levels():
    """Test tool permission levels."""
    echo = EchoTool()
    write = WriteFileTool()

    assert echo.permission_level == PermissionLevel.SAFE
    assert write.permission_level == PermissionLevel.CONFIRM
