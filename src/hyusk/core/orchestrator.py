"""Main orchestrator for Hyusk."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from hyusk.core.context import get_context_manager
from hyusk.llm.base import LLMResponse, StreamChunk
from hyusk.llm.messages import create_tool_result_message
from hyusk.llm.router import ModelType, get_router
from hyusk.logging import get_logger
from hyusk.models import Message, MessageRole

logger = get_logger(__name__)

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """You are Hyusk, an AI assistant that helps users with their computer tasks.

You can:
- Answer questions and provide information
- Execute commands and interact with the computer
- Read and write files
- Control applications
- Browse the web
- Run background agents for complex tasks

When using tools:
- Request tools when you need to perform actions
- Provide clear reasons for sensitive operations
- Be concise and direct in your responses
- Always confirm before destructive operations

You are running on {platform} and have access to the user's system through a secure tool execution layer."""


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    pass


class Orchestrator:
    """Main orchestrator for handling LLM interactions and tool execution."""

    def __init__(
        self,
        max_iterations: int = 10,
        timeout: int = 300,
    ):
        self.max_iterations = max_iterations
        self.timeout = timeout
        self.router = get_router()
        self.context_manager = get_context_manager()

    async def handle_request(
        self,
        user_message: str,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_type: str = ModelType.DEFAULT,
    ) -> LLMResponse:
        """Handle a user request and return the final response.

        Args:
            user_message: User's message
            conversation_id: Existing conversation ID
            task_id: Associated task ID
            system_prompt: Custom system prompt
            tools: Available tools
            model_type: Type of model to use

        Returns:
            Final LLM response

        Raises:
            OrchestratorError: If orchestration fails
        """
        logger.info(
            "Handling request",
            task_id=str(task_id) if task_id else None,
            model_type=model_type,
            has_tools=bool(tools),
        )

        # Create conversation if needed
        if conversation_id is None:
            conversation_id = uuid4()

        # Build context
        context = await self.context_manager.build_context(
            conversation_id=conversation_id,
            task_id=task_id,
            system_prompt=system_prompt or self._get_default_system_prompt(),
            tools=tools,
        )

        # Add user message
        user_msg = Message(
            role=MessageRole.USER,
            content=user_message,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        context["messages"].append(user_msg)

        # Save message
        await self.context_manager.save_message(user_msg, conversation_id, task_id)

        # Get provider
        provider = self.router.get_provider(model_type)

        # Orchestration loop
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1

            logger.info(
                f"Orchestration iteration {iteration}/{self.max_iterations}",
                message_count=len(context["messages"]),
            )

            # Get completion
            try:
                response = await provider.complete(
                    messages=context["messages"],
                    tools=context["tools"],
                    system=context["system"],
                )
            except Exception as e:
                logger.error(f"LLM completion failed: {e}")
                raise OrchestratorError(f"LLM completion failed: {e}")

            # Handle tool calls
            if response.has_tool_calls:
                logger.info(f"Processing {len(response.tool_calls)} tool calls")

                # Add assistant message with tool calls
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    conversation_id=conversation_id,
                    task_id=task_id,
                    metadata={"tool_calls": [tc.model_dump() for tc in response.tool_calls]},
                )
                context["messages"].append(assistant_msg)

                # Execute tools and add results
                from hyusk.tools.registry import get_registry

                tool_registry = get_registry()

                for tool_call in response.tool_calls:
                    logger.info(
                        f"Executing tool: {tool_call.tool_name}",
                        arguments=tool_call.arguments,
                    )

                    # Execute the tool with permission checking
                    tool_result = await tool_registry.execute_tool(tool_call, task_id=task_id)

                    # Convert to message
                    tool_result_msg = create_tool_result_message(
                        tool_call_id=tool_call.metadata.get("tool_use_id", str(tool_call.id)),
                        result=tool_result.output
                        if tool_result.status.value == "success"
                        else None,
                        error=tool_result.error,
                    )
                    tool_result_msg.conversation_id = conversation_id
                    tool_result_msg.task_id = task_id
                    context["messages"].append(tool_result_msg)

                # Continue loop to get next response
                continue

            # No tool calls, we're done
            logger.info("Request completed", iterations=iteration)

            # Add final assistant message
            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                conversation_id=conversation_id,
                task_id=task_id,
            )
            await self.context_manager.save_message(assistant_msg, conversation_id, task_id)

            return response

        # Hit max iterations
        logger.warning(f"Hit max iterations ({self.max_iterations})")
        raise OrchestratorError(f"Maximum iterations ({self.max_iterations}) exceeded")

    async def stream_request(
        self,
        user_message: str,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_type: str = ModelType.DEFAULT,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a response for a user request.

        Args:
            user_message: User's message
            conversation_id: Existing conversation ID
            task_id: Associated task ID
            system_prompt: Custom system prompt
            tools: Available tools
            model_type: Type of model to use

        Yields:
            StreamChunk instances
        """
        logger.info(
            "Starting streaming request",
            task_id=str(task_id) if task_id else None,
            model_type=model_type,
        )

        # Create conversation if needed
        if conversation_id is None:
            conversation_id = uuid4()

        # Build context
        context = await self.context_manager.build_context(
            conversation_id=conversation_id,
            task_id=task_id,
            system_prompt=system_prompt or self._get_default_system_prompt(),
            tools=tools,
        )

        # Add user message
        user_msg = Message(
            role=MessageRole.USER,
            content=user_message,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        context["messages"].append(user_msg)
        await self.context_manager.save_message(user_msg, conversation_id, task_id)

        # Get provider
        provider = self.router.get_provider(model_type)

        # Stream response
        try:
            async for chunk in provider.stream(
                messages=context["messages"],
                tools=context["tools"],
                system=context["system"],
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            raise OrchestratorError(f"Streaming failed: {e}")

    def _get_default_system_prompt(self) -> str:
        """Get the default system prompt with platform information."""
        import platform

        return DEFAULT_SYSTEM_PROMPT.format(platform=platform.system())


# Global orchestrator instance
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def set_orchestrator(orchestrator: Orchestrator) -> None:
    """Set the global orchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator
