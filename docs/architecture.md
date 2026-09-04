# Hyusk Architecture

This document describes the major interfaces and boundaries in Hyusk V3.
V1 laid out the core (errors, events, tools, permissions, agent loop,
sessions, platform, LLM abstraction). V2 layered a daemon + WebSocket
transport and streaming LLM responses. V3 layers **concurrent agent runs
with steering and cancellation** on top — without changing the core.

## Goals

1. A clean local CLI agent today (no daemon required).
2. A core that does not depend on any single model provider.
3. A core that does not depend on any single OS, but has explicit
   platform abstractions so additional platforms are additive.
4. The CLI is a thin client that talks to a long-running daemon.
5. Future clients (mobile, voice, remote, WebSocket) plug in without
   touching the core.
6. The agent loop is streaming-aware.
7. **The user can run multiple tasks in parallel and steer them.**
   The CLI stays responsive even while long tasks run.

## High-level shape

```
                ┌─────────────────────┐
                │     HYUSK CORE      │
                │                     │
                │  Agent / Loop       │
                │  Tool Registry      │
                │  Permission Policy  │
                │  Session Manager    │
                │  Event Bus          │
                │  LLM Provider       │
                └─────────┬───────────┘
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
   CLI (V3)         Voice (V4)         Mobile (V4)
   WebSocket         WebSocket          WebSocket
   client             client             client
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   HYUSK DAEMON      │
                │   WebSocket server  │
                │   (V3: concurrent   │
                │    tasks + ask      │
                │    routing)         │
                └─────────┬───────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   TASK MANAGER      │
                │   (V3)              │
                │  Owns a thread per  │
                │  task. Each task    │
                │  has its own        │
                │  Agent, session,    │
                │  and event stream.  │
                └─────────────────────┘
```

## V3 deltas

### `agent/tasks.py` — TaskManager

The single most important V3 addition. A `TaskManager` owns a registry of
`Task` objects. Each `Task` runs `Agent.run()` in its own thread with its
own `EventBus`. Tasks can run concurrently without blocking each other.

Public API:

- `TaskManager.submit(input_text=..., session=...)` — start a new task.
  Returns a `Task` handle. The agent begins running immediately.
- `Task.steer(message)` — queue a follow-up user message. The agent loop
  drains the queue between tool calls.
- `Task.cancel()` — request cancellation. The agent loop checks the
  cancel flag at safe points (between LLM calls, between tool calls).
- `Task.events()` — return a `(queue, unsubscribe)` pair. The queue
  receives every event the agent publishes. Safe to call before or
  after the task starts.
- `Task.info()` / `Task.result(timeout=None)` — snapshot the task state
  or block until it finishes.

**V3 design choice (and why we did it this way):** the Task has its own
internal subscribers list rather than routing events through the agent's
bus. The agent's bus already has a subscriber (the EventStream's
`on_event`) that puts events into the EventStream's queue. If we added
the daemon's queue subscriber directly to the bus, broadcasts would
trigger feedback loops (the queue subscriber would re-enqueue events
that the EventStream was also trying to deliver). The Task's separate
list, fed by the watcher thread that consumes the EventStream, avoids
this.

### `agent/loop.py` — steering + cancellation

The agent loop now:

- Calls `self._drain_steering(messages)` at the top of each iteration.
  This appends any queued follow-up user messages to the conversation.
- Checks `self._cancelled.is_set()` at the start of each iteration and
  between tool calls. The current tool call is allowed to finish; we do
  not interrupt it (that would require provider-specific cancellation
  which is V4 work).
- In streaming mode, also breaks out of the stream loop on cancel so
  the LLM call returns early.

`AgentLoopLimit` still propagates to callers (V2 contract preserved).
The `Task` wrapper catches it and sets state to `errored`.

### `daemon/server.py` — V3 protocol

The WebSocket protocol gained:

- `{"type": "run", ...}` now returns a `{"type": "task", "task_id": "...",
  "session_id": "..."}` message immediately, then streams events. The
  events are tagged with the `task_id` so multiple concurrent tasks can
  be multiplexed by the client.
- `{"type": "list_tasks"}` returns the current task list.
- `{"type": "cancel", "task_id": "..."}` cancels a task.
- `{"type": "steer", "task_id": "...", "input": "..."}` injects a
  follow-up user message.
- `{"type": "ask", ...}` is sent to the client that started the task
  when the policy says `ask`. The client replies with
  `{"type": "grant", "ask_id": "...", "granted": bool}`.

The daemon's `TaskManager` is created once at startup and shared by
all clients. Concurrent clients can submit, steer, and cancel tasks
independently.

### `client/client.py` — V3 client

The WebSocket client gained:

- A `DaemonClient` class that maintains a persistent connection and
  exposes `submit`, `cancel`, `steer`, `list_tasks`, `wait_done`,
  plus `on_event`, `on_ask`, `on_done`, `on_error` callbacks.
- `run_over_daemon_sync()` for one-shot use (the CLI uses it for
  one-shot commands).

### `cli/app.py` — V3 REPL

The REPL gained:

- `bg: <prompt>` — start a background task without waiting.
- `steer <id> <message>` — inject a follow-up.
- `cancel <id>` — cancel a running task.
- `tasks` — list active and recent tasks.

The `_render_event()` helper now prefixes output with `[task_id]` so
output from background tasks is distinguishable from foreground output.
In the daemon-backed REPL, all events from all running tasks are
rendered live.

### `sessions/store.py` — SessionStore

A small wrapper that knows the base directory for sessions. Each
`Task` holds a `Session` whose `metadata["_store_dir"]` is set by the
store, so the Task can save the session without re-passing the
directory.

## V1 + V2 modules (unchanged)

### `core/errors.py` — typed errors

`HyuskError` is the base. Subclasses: `ToolNotFound`, `PermissionDenied`,
`CommandFailed`, `Timeout`, `UnsupportedPlatform`, `FileNotFound`,
`InvalidInput`, `ProviderError`, `AgentLoopLimit`, `AgentCancelled`,
`AgentSteered`.

### `events/events.py` — typed event bus

`EventBus` is a synchronous pub/sub. `EventType` enum covers what the
agent and daemon need. V3 does not add new event types; existing ones
already cover concurrent task flows.

### `llm/` — providers

`LLMProvider.chat()` is the canonical contract. `chat_stream()` yields
`LLMChunk(text_delta, tool_call_delta, done, response)` for streaming
support. V2 added `OpenAICompatProvider.chat_stream()` and the
`AnthropicProvider`. V3 doesn't change these.

### `tools/` — tool base + registry

A `Tool` is a data record: name, description, JSON-schema input,
permission category, `execute()` callable. The agent discovers tools
through `ToolRegistry`; never hardcoded.

### `permissions/policy.py`

`PermissionPolicy` produces `allow` / `deny` / `ask` per call. The
daemon routes `ask` to the originating client.

### `platform/`

OS abstractions: `Shell` (subprocess), `ProcessManager` (Posix +
Windows stubs), `filesystem` helpers.

## V4+ paths (still no rewrite needed)

| V4+ feature              | Hook                                        |
|--------------------------|---------------------------------------------|
| Mobile client            | WebSocket protocol already supports all flows |
| Voice client             | Same protocol; push transcribed text into `run` |
| Persistent PTY shell     | swap `platform.shell.make_shell` factory    |
| Real Windows processes   | add `platform/windows/...`                  |
| Streaming cancellations  | provider-specific mid-stream abort          |
| Plugin marketplace       | dynamic Tool loading via the registry       |
| Sandboxing               | wrap `Tool.run` in a sandboxed executor     |
| Remote daemon            | add auth layer; protocol unchanged          |
| Multi-tenant daemon      | namespace sessions per client token         |

All of these only add code. Nothing in V1/V2/V3 needs to change.
