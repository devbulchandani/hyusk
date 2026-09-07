"""Tool registry for managing available tools."""

import asyncio
from typing import Any

from hyusk.logging import get_logger
from hyusk.models import PermissionLevel, ToolCall, ToolResult, ToolResultStatus
from hyusk.tools.base import Tool, ToolError, ToolTimeoutError

logger = get_logger(__name__)


class ToolRegistry:
    """Central registry for managing tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register

        Raises:
            ValueError: If tool name conflicts with existing tool
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name} is already registered")

        self._tools[tool.name] = tool
        logger.info(
            f"Registered tool: {tool.name}",
            category=tool.category,
            permission_level=tool.permission_level.value,
        )

    def unregister(self, tool_name: str) -> None:
        """Unregister a tool.

        Args:
            tool_name: Name of tool to unregister
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info(f"Unregistered tool: {tool_name}")

    def get(self, tool_name: str) -> Tool | None:
        """Get a tool by name.

        Args:
            tool_name: Tool name

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_name)

    def list_tools(
        self,
        category: str | None = None,
        permission_level: PermissionLevel | None = None,
    ) -> list[Tool]:
        """List all registered tools, optionally filtered.

        Args:
            category: Filter by category
            permission_level: Filter by permission level

        Returns:
            List of tools
        """
        tools = list(self._tools.values())

        if category:
            tools = [t for t in tools if t.category == category]

        if permission_level:
            tools = [t for t in tools if t.permission_level == permission_level]

        return tools

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all tools in LLM format.

        Returns:
            List of tool schemas
        """
        return [tool.to_dict() for tool in self._tools.values()]

    async def execute_tool(
        self,
        tool_call: ToolCall,
        timeout: int | None = None,
        task_id: Any = None,
    ) -> ToolResult:
        """Execute a tool call.

        Args:
            tool_call: Tool call to execute
            timeout: Optional timeout override
            task_id: Optional task ID for permission tracking

        Returns:
            ToolResult with execution outcome
        """
        tool = self.get(tool_call.tool_name)

        if not tool:
            logger.error(f"Tool not found: {tool_call.tool_name}")
            return ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.ERROR,
                error=f"Tool not found: {tool_call.tool_name}",
            )

        logger.info(
            f"Executing tool: {tool.name}",
            tool_call_id=str(tool_call.id),
            arguments=tool_call.arguments,
        )

        import time

        start_time = time.time()

        try:
            # Validate arguments
            tool.validate_arguments(tool_call.arguments)

            # Check permissions before execution
            from hyusk.permissions.engine import get_engine

            permission_engine = get_engine()
            permission_decision = await permission_engine.check_permission(
                tool_name=tool.name,
                permission_level=tool.permission_level,
                arguments=tool_call.arguments,
                task_id=task_id,
                reason=f"Tool requested by LLM: {tool.description}",
            )

            # If not approved, return error
            if not permission_decision.approved:
                logger.warning(
                    f"Tool execution denied: {tool.name}",
                    tool_call_id=str(tool_call.id),
                    reason=permission_decision.reason,
                )

                return ToolResult(
                    tool_call_id=tool_call.id,
                    status=ToolResultStatus.ERROR,
                    error=f"Permission denied: {permission_decision.reason}",
                )

            logger.info(
                f"Permission granted for tool: {tool.name}",
                tool_call_id=str(tool_call.id),
            )

            # Execute with timeout
            execution_timeout = timeout or tool.timeout

            try:
                result = await asyncio.wait_for(
                    tool.execute(**tool_call.arguments),
                    timeout=execution_timeout,
                )
            except asyncio.TimeoutError:
                raise ToolTimeoutError(f"Tool execution timed out after {execution_timeout}s")

            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Tool execution succeeded: {tool.name}",
                tool_call_id=str(tool_call.id),
                duration_ms=duration_ms,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.SUCCESS,
                output=result,
                duration_ms=duration_ms,
            )

        except ToolTimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(
                f"Tool execution timeout: {tool.name}",
                tool_call_id=str(tool_call.id),
                duration_ms=duration_ms,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.TIMEOUT,
                error=str(e),
                duration_ms=duration_ms,
            )

        except ToolError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"Tool execution error: {tool.name}",
                tool_call_id=str(tool_call.id),
                error=str(e),
                duration_ms=duration_ms,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.ERROR,
                error=str(e),
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(
                f"Unexpected error executing tool: {tool.name}",
                tool_call_id=str(tool_call.id),
                duration_ms=duration_ms,
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.ERROR,
                error=f"Unexpected error: {str(e)}",
                duration_ms=duration_ms,
            )

    def get_tool_count(self) -> int:
        """Get number of registered tools.

        Returns:
            Tool count
        """
        return len(self._tools)

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        logger.info("Cleared tool registry")


# Global tool registry instance
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def set_registry(registry: ToolRegistry) -> None:
    """Set the global tool registry instance."""
    global _registry
    _registry = registry
