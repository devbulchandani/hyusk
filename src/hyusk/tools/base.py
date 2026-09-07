"""Base tool interface."""

from abc import ABC, abstractmethod
from typing import Any

from hyusk.models import PermissionLevel, ToolSchema


class ToolError(Exception):
    """Base exception for tool errors."""

    pass


class ToolValidationError(ToolError):
    """Tool argument validation error."""

    pass


class ToolExecutionError(ToolError):
    """Tool execution error."""

    pass


class ToolTimeoutError(ToolError):
    """Tool execution timeout error."""

    pass


class Tool(ABC):
    """Abstract base class for all tools."""

    def __init__(self) -> None:
        """Initialize the tool."""
        self._validate_schema()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON schema for tool inputs."""
        pass

    @property
    def output_schema(self) -> dict[str, Any] | None:
        """JSON schema for tool outputs (optional)."""
        return None

    @property
    @abstractmethod
    def permission_level(self) -> PermissionLevel:
        """Permission level required to execute this tool."""
        pass

    @property
    def timeout(self) -> int:
        """Execution timeout in seconds."""
        return 30

    @property
    def category(self) -> str:
        """Tool category for organization."""
        return "general"

    @abstractmethod
    async def execute(self, **arguments: Any) -> Any:
        """Execute the tool with the given arguments.

        Args:
            **arguments: Tool-specific arguments matching input_schema

        Returns:
            Tool execution result

        Raises:
            ToolValidationError: If arguments are invalid
            ToolExecutionError: If execution fails
            ToolTimeoutError: If execution times out
        """
        pass

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        """Validate arguments against the input schema.

        Args:
            arguments: Arguments to validate

        Raises:
            ToolValidationError: If validation fails
        """
        # Basic validation - check required fields
        required_fields = self._get_required_fields()

        for field in required_fields:
            if field not in arguments:
                raise ToolValidationError(f"Missing required argument: {field}")

    def get_schema(self) -> ToolSchema:
        """Get the complete tool schema.

        Returns:
            ToolSchema object
        """
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert tool to dictionary format for LLM.

        Returns:
            Dictionary with tool information
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def _get_required_fields(self) -> list[str]:
        """Extract required fields from input schema.

        Returns:
            List of required field names
        """
        return self.input_schema.get("required", [])

    def _validate_schema(self) -> None:
        """Validate that the tool schema is properly defined."""
        if not self.name:
            raise ValueError("Tool must have a name")

        if not self.description:
            raise ValueError("Tool must have a description")

        if not isinstance(self.input_schema, dict):
            raise ValueError("Tool input_schema must be a dictionary")

        if "type" not in self.input_schema:
            raise ValueError("Tool input_schema must have a 'type' field")


class SafeTool(Tool):
    """Base class for safe tools that don't require permissions."""

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE


class ConfirmTool(Tool):
    """Base class for tools that require user confirmation."""

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CONFIRM


class SensitiveTool(Tool):
    """Base class for sensitive tools requiring explicit approval."""

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE
