"""Tool loader for registering default tools."""

from hyusk.computer import (
    ClickMouseTool,
    CloseApplicationTool,
    GetWindowListTool,
    OpenApplicationTool,
    PressKeyTool,
    TakeScreenshotTool,
    TypeTextTool,
)
from hyusk.logging import get_logger
from hyusk.tools.basic import CalculatorTool, EchoTool, GetSystemInfoTool, GetTimeTool
from hyusk.tools.filesystem import (
    CopyFileTool,
    CreateDirectoryTool,
    DeleteFileTool,
    FileExistsTool,
    ListDirectoryTool,
    MoveFileTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from hyusk.tools.registry import get_registry
from hyusk.tools.terminal import (
    ProcessStartTool,
    ProcessStatusTool,
    ProcessStopTool,
    TerminalExecuteTool,
)

logger = get_logger(__name__)


def load_default_tools() -> None:
    """Load all default tools into the registry."""
    registry = get_registry()

    # Basic tools
    tools_to_register = [
        # System
        GetTimeTool(),
        GetSystemInfoTool(),
        # Utility
        EchoTool(),
        CalculatorTool(),
        # Filesystem - Safe
        ReadFileTool(),
        ListDirectoryTool(),
        FileExistsTool(),
        SearchFilesTool(),
        # Filesystem - Confirm
        WriteFileTool(),
        CopyFileTool(),
        MoveFileTool(),
        DeleteFileTool(),
        CreateDirectoryTool(),
        # Terminal - Sensitive
        TerminalExecuteTool(),
        ProcessStartTool(),
        ProcessStopTool(),
        # Process - Safe
        ProcessStatusTool(),
        # Computer Control - Safe
        OpenApplicationTool(),
        TakeScreenshotTool(),
        GetWindowListTool(),
        # Computer Control - Confirm
        CloseApplicationTool(),
        # Computer Control - Sensitive
        TypeTextTool(),
        PressKeyTool(),
        ClickMouseTool(),
    ]

    for tool in tools_to_register:
        try:
            registry.register(tool)
        except Exception as e:
            logger.error(f"Failed to register tool {tool.name}: {e}")

    logger.info(f"Loaded {len(tools_to_register)} default tools")


def load_safe_tools_only() -> None:
    """Load only safe tools (no confirmation required)."""
    registry = get_registry()

    tools_to_register = [
        GetTimeTool(),
        GetSystemInfoTool(),
        EchoTool(),
        CalculatorTool(),
        ReadFileTool(),
        ListDirectoryTool(),
        FileExistsTool(),
        SearchFilesTool(),
        ProcessStatusTool(),
        OpenApplicationTool(),
        TakeScreenshotTool(),
        GetWindowListTool(),
    ]

    for tool in tools_to_register:
        try:
            registry.register(tool)
        except Exception as e:
            logger.error(f"Failed to register tool {tool.name}: {e}")

    logger.info(f"Loaded {len(tools_to_register)} safe tools")
