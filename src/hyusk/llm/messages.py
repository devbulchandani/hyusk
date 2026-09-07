"""Message conversion utilities for LLM providers."""

import json
from typing import Any

from hyusk.models import Message, MessageRole


def message_to_dict(message: Message) -> dict[str, Any]:
    """Convert a Message to a dictionary format.

    Args:
        message: Message to convert

    Returns:
        Dictionary representation
    """
    # Simple text message
    if isinstance(message.content, str):
        return {
            "role": message.role.value,
            "content": message.content,
        }

    # Multimodal message
    content_parts = []
    for part in message.content:
        if part.type == "text" and part.text:
            content_parts.append({"type": "text", "text": part.text})
        elif part.type == "image" and part.image_url:
            content_parts.append(
                {
                    "type": "image",
                    "source": {"type": "url", "url": part.image_url},
                }
            )
        elif part.type == "image" and part.image_data:
            # Base64 encoded image data
            import base64

            b64_data = base64.b64encode(part.image_data).decode("utf-8")
            content_parts.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "data": b64_data},
                }
            )

    return {
        "role": message.role.value,
        "content": content_parts,
    }


def messages_to_anthropic_format(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert messages to Anthropic format.

    Args:
        messages: List of messages

    Returns:
        Messages in Anthropic format
    """
    anthropic_messages = []

    for msg in messages:
        # Skip system messages (handled separately in Anthropic)
        if msg.role == MessageRole.SYSTEM:
            continue

        # Convert tool results to user messages with tool_result content
        if msg.role == MessageRole.TOOL:
            # Tool results are formatted specially for Anthropic
            if isinstance(msg.content, str):
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.metadata.get("tool_call_id", "unknown"),
                                "content": msg.content,
                            }
                        ],
                    }
                )
            continue

        anthropic_messages.append(message_to_dict(msg))

    return anthropic_messages


def messages_to_openai_format(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert messages to OpenAI format.

    Args:
        messages: List of messages

    Returns:
        Messages in OpenAI format
    """
    openai_messages = []

    for msg in messages:
        # Tool messages need special handling in OpenAI
        if msg.role == MessageRole.TOOL:
            openai_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.metadata.get("tool_call_id", "unknown"),
                    "content": msg.text_content,
                }
            )
            continue

        # Regular messages
        msg_dict = message_to_dict(msg)

        # OpenAI uses different image format
        if isinstance(msg.content, list):
            content_parts = []
            for part in msg.content:
                if part.type == "text" and part.text:
                    content_parts.append({"type": "text", "text": part.text})
                elif part.type == "image":
                    if part.image_url:
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": part.image_url},
                            }
                        )
                    elif part.image_data:
                        import base64

                        b64_data = base64.b64encode(part.image_data).decode("utf-8")
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64_data}"},
                            }
                        )

            msg_dict["content"] = content_parts

        # If this is an assistant message with tool calls in metadata, add them
        if msg.role == MessageRole.ASSISTANT and "tool_calls" in msg.metadata:
            tool_calls_data = msg.metadata["tool_calls"]
            if tool_calls_data:
                msg_dict["tool_calls"] = []
                for tc in tool_calls_data:
                    msg_dict["tool_calls"].append({
                        "id": tc.get("metadata", {}).get("tool_call_id", f"call_{tc.get('id', 'unknown')}"),
                        "type": "function",
                        "function": {
                            "name": tc.get("tool_name", ""),
                            "arguments": json.dumps(tc.get("arguments", {})),
                        }
                    })

        openai_messages.append(msg_dict)

    return openai_messages


def create_tool_result_message(
    tool_call_id: str,
    result: Any,
    error: str | None = None,
) -> Message:
    """Create a tool result message.

    Args:
        tool_call_id: ID of the tool call
        result: Tool execution result
        error: Error message if tool failed

    Returns:
        Message with tool result
    """
    if error:
        content = f"Error: {error}"
    else:
        # Convert result to string representation
        if isinstance(result, str):
            content = result
        elif isinstance(result, dict) or isinstance(result, list):
            content = json.dumps(result, indent=2)
        else:
            content = str(result)

    return Message(
        role=MessageRole.TOOL,
        content=content,
        metadata={"tool_call_id": tool_call_id},
    )


def truncate_messages(
    messages: list[Message],
    max_messages: int = 50,
    keep_system: bool = True,
) -> list[Message]:
    """Truncate message history to fit context window.

    Args:
        messages: All messages
        max_messages: Maximum number of messages to keep
        keep_system: Always keep system messages

    Returns:
        Truncated message list
    """
    if len(messages) <= max_messages:
        return messages

    # Separate system and non-system messages
    system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
    other_messages = [m for m in messages if m.role != MessageRole.SYSTEM]

    # Keep most recent messages
    kept_messages = other_messages[-(max_messages - len(system_messages)) :]

    # Combine back
    if keep_system:
        return system_messages + kept_messages
    else:
        return kept_messages
