# Hyusk Architecture

## Overview

Hyusk is built with a clean layered architecture that separates concerns and ensures the LLM never bypasses security:

```
┌──────────────────────────────────────┐
│           INTERFACES                  │
│   (Voice, CLI, Phone, Web)           │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│         HYUSK CORE                    │
│                                       │
│  • Orchestrator                       │
│  • Context Manager                    │
│  • Task Manager                       │
│  • Agent Manager                      │
│  • Memory                             │
│  • Event Bus                          │
│  • Scheduler                          │
│                                       │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│      PERMISSION ENGINE                │
│                                       │
│  • Policy Evaluation                  │
│  • Approval Management                │
│  • Security Rules                     │
│                                       │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│        LLM ROUTER                     │
│                                       │
│  • Provider Selection                 │
│  • Model Routing                      │
│  • Tool Call Formatting               │
│                                       │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│       TOOL SYSTEM                     │
│                                       │
│  • Tool Registry                      │
│  • Execution Engine                   │
│  • Result Handling                    │
│                                       │
└──────────────┬───────────────────────┘
               │
               ▼
    ┌────────────────────┐
    │   EXTERNAL WORLD   │
    │                    │
    │ • Computer         │
    │ • Filesystem       │
    │ • Terminal         │
    │ • Applications     │
    │ • Services         │
    │ • Agents           │
    └────────────────────┘
```

## Core Principles

### 1. Security First

The LLM decides **what** it wants to do. The permission engine decides **whether** it's allowed. The tool system performs the actual operation.

```
LLM: "I want to delete file X"
  ↓
Permission Engine: "Delete operations require confirmation"
  ↓
User: Approves/Rejects
  ↓
Tool: Executes or blocks
```

### 2. Platform Abstraction

OS-specific code is isolated behind interfaces:

```python
# Abstract interface
class ComputerController:
    async def open_app(self, name: str) -> None:
        pass

# Platform-specific implementation
class MacOSController(ComputerController):
    async def open_app(self, name: str) -> None:
        # macOS-specific implementation
        pass
```

### 3. Component Independence

Components communicate through well-defined interfaces and the event bus:

- Tools don't know about the LLM
- The LLM doesn't know about specific tool implementations
- Agents run independently of the main conversation loop
- Voice, CLI, and remote interfaces use the same core

### 4. Fail-Safe Design

No single component failure should crash the entire system:

- Agent crashes → logged, task marked failed, Hyusk continues
- LLM API failure → error handling, potential fallback to local model
- Tool failure → error returned to LLM, recovery attempted
- Event handler exception → logged, other handlers continue

## Key Components

### Core

**Orchestrator**: Central coordinator that manages the conversation loop and tool execution.

**Context Manager**: Constructs appropriate context for LLM requests (messages, tools, memory).

**Lifecycle Manager**: Handles startup, shutdown, and component initialization.

### Event Bus

Decoupled event system for component communication:

```python
# Subscribe
await event_bus.subscribe(EventType.TASK_COMPLETED, handler)

# Publish
await event_bus.emit(EventType.TASK_COMPLETED, data={...})
```

Events enable:
- Notification system
- Remote UI updates
- Scheduler triggers
- Memory updates
- Logging and observability

### LLM Layer

**Provider Abstraction**: Unified interface for different LLM providers (Anthropic, OpenAI, local models).

**Router**: Selects appropriate model based on task requirements (fast, coding, vision).

**Message Handler**: Converts between Hyusk's internal message format and provider formats.

### Tool System

**Tool Registry**: Central registry of available tools with schemas and metadata.

**Tool**: Abstract base class for all tools:

```python
class Tool:
    name: str
    description: str
    permission_level: PermissionLevel
    input_schema: dict
    
    async def execute(self, arguments: dict) -> Any:
        pass
```

**Tool Categories**:
- Filesystem: read, write, search, edit
- Terminal: execute, start process, monitor
- Computer: screenshot, click, type, open app
- Browser: navigate, extract, interact
- Integration: GitHub, calendar, email, music

### Permission System

**Permission Levels**:
- `SAFE`: Auto-approved (read file, screenshot)
- `CONFIRM`: Requires confirmation (write file, terminal)
- `SENSITIVE`: Explicit approval (delete, credentials)
- `BLOCKED`: Never allowed

**Approval Flow**:
1. Tool requested by LLM
2. Permission engine evaluates policy
3. If confirmation needed, creates PermissionRequest
4. User approves/rejects via CLI/voice/phone
5. Decision stored and enforced

### Task System

Every background operation becomes a persistent Task:

```python
task = Task(
    type=TaskType.AGENT,
    description="Fix failing tests",
    status=TaskStatus.RUNNING
)
```

Tasks can be:
- Listed and inspected
- Cancelled
- Retried
- Monitored via events

### Agent System

Agents are isolated task executors with:
- Dedicated workspace
- Specific permissions
- Independent process
- Supervision and recovery

Types:
- Coding: repository inspection, editing, testing
- General: arbitrary tasks
- Research: web search, information gathering
- Browser: web automation
- Monitoring: system observation

### Memory System

Structured memory storage:

**Memory Types**:
- Conversation: recent interaction context
- Task: information about completed tasks
- Project: codebase understanding
- Preference: user preferences
- Long-term: important facts

**Retrieval**: Context-aware memory search to augment LLM context without overwhelming it.

### Database

SQLite for persistence:
- Tasks and their states
- Agent execution history
- Permission requests and decisions
- Events
- Memory entries
- Scheduled tasks
- Conversations

## Data Flow

### Typical Request Flow

1. **Input**: User sends command (voice/CLI/phone)

2. **Context Construction**:
   - Load relevant conversation history
   - Retrieve relevant memory
   - Gather available tools
   - Include current task context

3. **LLM Request**:
   - Route to appropriate model
   - Stream response
   - Extract tool calls

4. **Tool Execution**:
   - Validate tool call schema
   - Check permissions
   - Request approval if needed
   - Execute tool
   - Capture result

5. **Iteration**:
   - Return result to LLM
   - LLM decides next action
   - Repeat until complete

6. **Response**:
   - Generate final response
   - Update memory
   - Emit events
   - Return to user

### Agent Execution Flow

1. User requests agent: "Start coding agent to fix tests"
2. Task created with type=AGENT
3. Agent manager creates Agent instance
4. Workspace allocated (git worktree, temp directory, etc.)
5. Agent process spawned with:
   - Isolated permissions
   - Dedicated LLM context
   - Workspace access
6. Agent runs autonomously:
   - Inspects code
   - Makes changes
   - Runs tests
   - Emits progress events
7. On completion:
   - Results saved
   - Workspace cleaned (if configured)
   - Completion event emitted
   - User notified

## Security Model

### Defense in Depth

1. **Schema Validation**: All tool arguments validated against schema
2. **Permission Checks**: Every tool call evaluated by permission engine
3. **Path Validation**: Filesystem operations restricted to allowed paths
4. **Command Inspection**: Terminal commands analyzed for risk
5. **Approval Flow**: Sensitive operations require explicit approval
6. **Audit Logging**: All operations logged with full context
7. **Secret Redaction**: Credentials never logged or shown to LLM
8. **Agent Isolation**: Agents run in isolated workspaces with limited permissions

### Threat Model

**Protected Against**:
- Arbitrary code execution without approval
- Unintended file deletion
- Credential exposure
- Path traversal attacks
- Prompt injection leading to harmful actions

**Not Protected Against** (by design):
- User explicitly approving malicious operations
- Authorized operations with unintended side effects

## Extension Points

### Adding a New Tool

1. Create tool class implementing `Tool` interface
2. Define schema and permission level
3. Implement `execute` method
4. Register with tool registry
5. Add tests

### Adding a New LLM Provider

1. Implement `LLMProvider` interface
2. Handle message conversion
3. Support tool calling format
4. Add to router configuration
5. Add tests

### Adding a New Platform

1. Implement platform-specific controllers under `computer/<platform>/`
2. Follow existing abstract interfaces
3. Platform selected via configuration
4. Contribute back (please!)

## Future Architecture

### Rust Components (Later)

Performance-critical components may migrate to Rust:
- `hyusk-daemon`: System daemon with IPC
- `hyusk-audio-runtime`: Voice processing pipeline
- `hyusk-sandbox`: Agent isolation
- `hyusk-ipc`: Inter-process communication

Python remains the orchestration layer. Rust handles performance bottlenecks.

### Distributed Agents (Later)

Agents could run on separate machines:
- Workstation: Main Hyusk instance
- Cloud: Resource-intensive agents
- Phone: Local voice processing

All coordinated through events and remote API.

## Testing Strategy

### Unit Tests
- Models and schemas
- Configuration
- Event bus
- Permission engine
- Individual tools (mocked I/O)

### Integration Tests
- Tool calling end-to-end
- Task lifecycle
- Agent execution
- Database persistence
- CLI commands

### Security Tests
- Path traversal
- Permission bypass attempts
- Command injection
- Secret leakage
- Invalid tool arguments

## Observability

### Logging

Structured JSON logs with:
- Timestamp
- Component
- Task ID
- Agent ID
- Tool name
- Duration
- Status

### Events

All significant operations emit events:
- Task lifecycle
- Agent progress
- Tool execution
- Permission requests
- System state changes

### Monitoring

Future: Metrics, traces, and dashboards for:
- Task throughput
- Agent success rate
- LLM usage and costs
- Tool execution times
- Error rates

## Configuration

Configuration layers (precedence):
1. Environment variables
2. `.env` file
3. `~/.config/hyusk/config.yaml`
4. Code defaults

Configuration is immutable after initialization. Changes require restart.

## Development Workflow

1. **Design**: Plan architecture for new feature
2. **Implement**: Write code following patterns
3. **Test**: Unit and integration tests
4. **Lint**: Run ruff and mypy
5. **Manual Test**: Verify real-world behavior
6. **Document**: Update relevant docs
7. **Commit**: Meaningful commit message
8. **Iterate**: Improve based on feedback

---

This architecture provides a solid foundation for a production-quality AI operating system that is secure, extensible, and maintainable.
