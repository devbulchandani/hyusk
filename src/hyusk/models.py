"""Core domain models for Hyusk."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ============================================================================
# MESSAGE MODELS
# ============================================================================


class MessageRole(str, Enum):
    """Role of a message in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageContent(BaseModel):
    """Content of a message, supporting multimodal data."""

    type: str  # text, image, audio_metadata, tool_result
    text: str | None = None
    image_url: str | None = None
    image_data: bytes | None = None
    data: dict[str, Any] | None = None


class Message(BaseModel):
    """A message in a conversation."""

    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: list[MessageContent] | str
    conversation_id: UUID | None = None
    task_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def text_content(self) -> str:
        """Extract text content from the message."""
        if isinstance(self.content, str):
            return self.content
        text_parts = [c.text for c in self.content if c.type == "text" and c.text]
        return " ".join(text_parts)


class Conversation(BaseModel):
    """A conversation containing multiple messages."""

    id: UUID = Field(default_factory=uuid4)
    messages: list[Message] = Field(default_factory=list)
    task_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# TOOL MODELS
# ============================================================================


class PermissionLevel(str, Enum):
    """Permission level required for a tool."""

    SAFE = "safe"  # No approval needed
    CONFIRM = "confirm"  # Requires user confirmation
    SENSITIVE = "sensitive"  # Requires explicit approval
    BLOCKED = "blocked"  # Not allowed


class ToolSchema(BaseModel):
    """Schema definition for a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


class ToolCall(BaseModel):
    """A request to execute a tool."""

    id: UUID = Field(default_factory=uuid4)
    tool_name: str
    arguments: dict[str, Any]
    task_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultStatus(str, Enum):
    """Status of a tool execution result."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PERMISSION_DENIED = "permission_denied"


class ToolResult(BaseModel):
    """Result of a tool execution."""

    id: UUID = Field(default_factory=uuid4)
    tool_call_id: UUID
    status: ToolResultStatus
    output: Any = None
    error: str | None = None
    duration_ms: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# PERMISSION MODELS
# ============================================================================


class PermissionRequestStatus(str, Enum):
    """Status of a permission request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PermissionRequest(BaseModel):
    """Request for permission to execute a tool."""

    id: UUID = Field(default_factory=uuid4)
    task_id: UUID | None = None
    tool: str  # Tool name
    arguments: dict[str, Any] = Field(default_factory=dict)  # Tool arguments
    reason: str | None = None
    status: PermissionRequestStatus = PermissionRequestStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionDecision(BaseModel):
    """Decision on a permission request."""

    request_id: UUID | None = None
    approved: bool
    reason: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================================
# TASK MODELS
# ============================================================================


class TaskStatus(str, Enum):
    """Status of a task."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Type of task."""

    USER_COMMAND = "user_command"
    AGENT = "agent"
    SCHEDULED = "scheduled"
    EVENT_TRIGGERED = "event_triggered"


class Task(BaseModel):
    """A task in the system."""

    id: UUID = Field(default_factory=uuid4)
    type: TaskType
    description: str
    status: TaskStatus = TaskStatus.QUEUED
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    priority: int = 0
    result: Any | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# AGENT MODELS
# ============================================================================


class AgentStatus(str, Enum):
    """Status of an agent."""

    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentType(str, Enum):
    """Type of agent."""

    CODING = "coding"
    GENERAL = "general"
    RESEARCH = "research"
    BROWSER = "browser"
    MONITORING = "monitoring"


class Agent(BaseModel):
    """An agent executing a task."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    type: AgentType
    task_id: UUID
    status: AgentStatus = AgentStatus.STARTING
    model: str
    workspace: str | None = None
    permissions: list[str] = Field(default_factory=list)
    process_id: int | None = None
    result: Any | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """An event from an agent."""

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# MEMORY MODELS
# ============================================================================


class MemoryType(str, Enum):
    """Type of memory."""

    CONVERSATION = "conversation"
    TASK = "task"
    PROJECT = "project"
    PREFERENCE = "preference"
    LONG_TERM = "long_term"


class Memory(BaseModel):
    """A memory entry."""

    id: UUID = Field(default_factory=uuid4)
    type: MemoryType
    content: str
    summary: str | None = None
    task_id: UUID | None = None
    conversation_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    importance: float = 0.5  # 0.0 to 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    accessed_at: datetime = Field(default_factory=datetime.utcnow)
    access_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# EVENT MODELS
# ============================================================================


class EventType(str, Enum):
    """Type of system event."""

    # Task events
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_PROGRESS = "agent.progress"
    AGENT_WAITING = "agent.waiting"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    # Permission events
    APPROVAL_CREATED = "approval.created"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"

    # System events
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"


class Event(BaseModel):
    """A system event."""

    id: UUID = Field(default_factory=uuid4)
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    task_id: UUID | None = None
    agent_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# SCHEDULED TASK MODELS
# ============================================================================


class ScheduleType(str, Enum):
    """Type of schedule."""

    ONCE = "once"
    PERIODIC = "periodic"
    CRON = "cron"
    EVENT_TRIGGERED = "event_triggered"


class ScheduledTask(BaseModel):
    """A scheduled task."""

    id: UUID = Field(default_factory=uuid4)
    schedule_type: ScheduleType
    description: str
    task_type: TaskType
    task_data: dict[str, Any] = Field(default_factory=dict)
    schedule_config: dict[str, Any] = Field(default_factory=dict)  # cron, interval, etc.
    next_run: datetime | None = None
    last_run: datetime | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
