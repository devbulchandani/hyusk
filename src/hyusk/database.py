"""Database layer for Hyusk using SQLAlchemy."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hyusk.config import get_config
from hyusk.logging import get_logger
from hyusk.models import (
    AgentStatus,
    AgentType,
    EventType,
    MemoryType,
    MessageRole,
    PermissionRequestStatus,
    ScheduleType,
    TaskStatus,
    TaskType,
    ToolResultStatus,
)

logger = get_logger(__name__)


# ============================================================================
# Base
# ============================================================================


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


# ============================================================================
# Database Models
# ============================================================================


class MessageDB(Base):
    """Database model for messages."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)  # JSON serialized
    conversation_id: Mapped[UUID | None]
    task_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ConversationDB(Base):
    """Database model for conversations."""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ToolCallDB(Base):
    """Database model for tool calls."""

    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tool_name: Mapped[str] = mapped_column(String(255))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    task_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ToolResultDB(Base):
    """Database model for tool results."""

    __tablename__ = "tool_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tool_call_id: Mapped[UUID]
    status: Mapped[ToolResultStatus] = mapped_column(Enum(ToolResultStatus))
    output: Mapped[str | None] = mapped_column(Text)  # JSON serialized
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PermissionRequestDB(Base):
    """Database model for permission requests."""

    __tablename__ = "permission_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID | None]
    tool: Mapped[str] = mapped_column(String(255))  # Tool name
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # Tool arguments
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PermissionRequestStatus] = mapped_column(Enum(PermissionRequestStatus))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TaskDB(Base):
    """Database model for tasks."""

    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[TaskType] = mapped_column(Enum(TaskType))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.QUEUED)
    agent_id: Mapped[UUID | None]
    conversation_id: Mapped[UUID | None]
    priority: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text)  # JSON serialized
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentDB(Base):
    """Database model for agents."""

    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[AgentType] = mapped_column(Enum(AgentType))
    task_id: Mapped[UUID]
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), default=AgentStatus.STARTING)
    model: Mapped[str] = mapped_column(String(255))
    workspace: Mapped[str | None] = mapped_column(String(1024))
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=list)  # List of permissions
    process_id: Mapped[int | None]
    result: Mapped[str | None] = mapped_column(Text)  # JSON serialized
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EventDB(Base):
    """Database model for events."""

    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[EventType] = mapped_column(Enum(EventType))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task_id: Mapped[UUID | None]
    agent_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MemoryDB(Base):
    """Database model for memory entries."""

    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[MemoryType] = mapped_column(Enum(MemoryType))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[UUID | None]
    conversation_id: Mapped[UUID | None]
    tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=list)  # List of tags
    importance: Mapped[float] = mapped_column(default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ScheduledTaskDB(Base):
    """Database model for scheduled tasks."""

    __tablename__ = "scheduled_tasks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    schedule_type: Mapped[ScheduleType] = mapped_column(Enum(ScheduleType))
    description: Mapped[str] = mapped_column(Text)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType))
    task_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    next_run: Mapped[datetime | None] = mapped_column(DateTime)
    last_run: Mapped[datetime | None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ============================================================================
# Database Management
# ============================================================================


class Database:
    """Database connection and session management."""

    def __init__(self, database_url: str | None = None):
        """Initialize database connection.

        Args:
            database_url: Database URL, defaults to config value
        """
        if database_url is None:
            config = get_config()
            database_url = config.database.url

        # Expand ~ in path for SQLite databases
        if database_url.startswith("sqlite"):
            database_url = database_url.replace("~", str(Path.home()))

        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Initialize database tables."""
        logger.info("Initializing database")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database initialized successfully")

    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()
        logger.info("Database connections closed")

    def get_session(self) -> AsyncSession:
        """Get a new database session.

        Returns:
            AsyncSession instance
        """
        return self.session_factory()


# Global database instance
_database: Database | None = None


def get_database() -> Database:
    """Get the global database instance."""
    global _database
    if _database is None:
        _database = Database()
    return _database


def set_database(database: Database) -> None:
    """Set the global database instance."""
    global _database
    _database = database
