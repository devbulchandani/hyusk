# Hyusk Architecture

This document describes the major interfaces and boundaries in Hyusk V2.
V1 already laid out the core (errors, events, tools, permissions, agent
loop, sessions, platform, LLM abstraction). V2 layers a daemon +
WebSocket transport and streaming LLM responses on top — without
changing the core.

## Goals

V1 goals still apply:

1. A clean local CLI agent today (no daemon required).
2. A core that does not depend on any single model provider.
3. A core that does not depend on any single OS, but has explicit platform
   abstractions so additional platforms are additive.

V2 goals:

4. The CLI should be a **thin client** that talks to a long-running
   daemon when one is available.
5. Future clients (mobile, voice, remote, WebSocket) plug in without
   touching the core.
6. The agent loop should be **streaming-aware**: providers that support
   SSE should drive text deltas into the event bus in real time.

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
   CLI (V1+V2)     Voice (V3)         Mobile (V3)
   WebSocket         WebSocket          WebSocket
   client            client             client
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   HYUSK DAEMON      │
                │   WebSocket server  │
                │   (V2)              │
                └─────────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   PROVIDERS         │
                │   OpenAI-compat     │
                │   Anthropic         │
                │   (V2)              │
                └─────────────────────┘
```

The dashed boxes above the core are V2+ clients. The daemon speaks a
small JSON protocol; the V2 CLI is one of those clients.

## V2 deltas

### `daemon/` — WebSocket server

`daemon/server.py` runs an asyncio WebSocket server. It owns a
`DaemonContext` containing the registry, policy, LLM, and session
directory. It uses `websockets` (only V2 runtime dep).

Protocol messages (`client → server` and `server → client`) are documented
in `README.md`. The protocol is intentionally tiny — there is no separate
streaming message type; events already stream because each one is its
own JSON message.

`run_session()` uses `EventStream` (in `agent/loop.py`) to consume the
agent's events on a reader thread, then forwards them to the WebSocket
from the asyncio loop via a queue. This avoids `run_in_executor` traps
(StopIteration).

Lifecycle:

- `pid_file()` writes the daemon PID to `<config>/daemon.pid`.
- `is_running()` checks if the PID is alive.
- `serve_forever()` is the foreground entry; `cli/app.py` calls it from
  `hyusk --daemon-action start`.
- `hyusk --daemon-action stop` sends SIGTERM and waits for the pid file
  to be cleared.

### `client/` — WebSocket client

`client/client.py` exposes `run_over_daemon_sync()` and
`list_sessions_sync()`. The CLI uses these when the daemon is
reachable. The CLI replays the collected events through the same
`_render_event()` function used in-process, so the user experience is
identical whether the daemon is running or not.

### `llm/provider.py` — streaming

`LLMProvider` now also exposes `chat_stream()`. It yields
`LLMChunk(text_delta=..., tool_call_delta=..., done=..., response=...)`.
The default `chat_stream()` simply wraps `chat()` and yields a single
`done` chunk, so providers that do not override it still work.

`LLMChunk` has:

- `text_delta`: a partial text fragment.
- `tool_call_delta`: an optional partial or complete `ToolCallRequest`.
- `done`: signals the final chunk; `response` holds the complete
  `LLMResponse`.

### `llm/openai_compat.py` — real SSE streaming

V2 implements proper SSE streaming against `/chat/completions?stream=true`.
It accumulates text deltas into `accumulated_text` and tool call JSON
into `tool_state`. When the stream ends, the final `LLMResponse` is
yielded as a `done` chunk.

### `llm/anthropic.py` — new in V2

Anthropic Messages API provider, streaming + non-streaming. Uses
`urllib` so there is no SDK dependency.

Differences vs OpenAI:

- System messages are a top-level `system` field, not a message.
- Tools use `input_schema` directly (no `function` wrapper).
- Tool calls are `tool_use` content blocks; tool results are
  `tool_result` blocks in a user message.
- The streaming protocol uses `event:` lines with types
  `message_start`, `content_block_start`, `content_block_delta`,
  `content_block_stop`, `message_delta`, `message_stop`, `ping`.

`_convert_messages()` translates between Hyusk's OpenAI-style
`role=tool` messages and Anthropic's `tool_result` blocks.

### `agent/loop.py` — streaming-aware

The agent loop detects whether the LLM provider overrides
`chat_stream()`. If it does, the loop consumes the stream and emits one
`AGENT_TEXT` event per text chunk with `delta=True`. If it does not, the
loop falls back to `chat()` and emits one `AGENT_TEXT` event with
`delta=False`. CLI renderers use the `delta` flag to decide between
"streamed partial" and "complete response".

A new `EventStream` class runs the agent in a background thread and
yields events from the calling thread. Transports (the daemon) consume
it through a queue.

### `cli/app.py` — client + daemon subcommands

- `hyusk [PROMPT]` — REPL or one-shot.
- `hyusk --daemon-action start|stop|status` — daemon lifecycle.
- `hyusk --list-sessions` — list sessions (asks the daemon if reachable,
  falls back to local listing).
- `hyusk --no-daemon` — force in-process agent.
- `hyusk --daemon-only` — fail if the daemon is unreachable.

If a prompt is supplied, the CLI uses `_run_one_shot()`. If not, it
uses `_run_repl()`. Both have `_via_daemon` and in-process variants;
the same `_render_event()` is used in both modes.

Legacy `hyusk daemon start` / `hyusk sessions` syntax is accepted
through `_normalize_argv()` and translated into flag form.

## Core modules (V1, unchanged)

### `core/errors.py` — typed errors

All Hyusk-specific errors subclass `HyuskError`. The agent and the
daemon translate them into friendly messages. Generic exceptions are
never silently swallowed.

### `events/events.py` — typed event bus

The event bus is the only seam between the agent and any transport.
V2 does not add new event types; existing ones already cover what the
daemon needs:

| Event              | Data                                         |
|--------------------|---------------------------------------------|
| `agent.started`    | message count                               |
| `agent.thinking`   | iteration number                            |
| `agent.text`       | `{delta: bool, text: str}`                  |
| `agent.tool_call`  | available tool names                        |
| `tool.started`     | `{name, arguments}`                         |
| `tool.completed`   | `{name, duration_ms, error}`                |
| `agent.completed`  | `{iterations, text_chars}`                  |
| `agent.error`      | `{error}`                                   |

### `llm/provider.py` — LLM abstraction

```python
class LLMProvider(abc.ABC):
    name: str
    def chat(self, messages, tools=None, *, model=None, temperature=None) -> LLMResponse: ...
    def chat_stream(self, messages, tools=None, *, model=None, temperature=None) -> Iterator[LLMChunk]: ...
```

V2 still keeps `chat()` as the canonical contract. New providers must
implement `chat()` and should override `chat_stream()` for real-time
rendering.

### `tools/` — tools

A `Tool` is a data record: name, description, JSON-schema input,
permission category, `execute()` callable. The agent discovers tools
through `ToolRegistry`; never hardcoded.

### `permissions/policy.py`

`PermissionPolicy` produces `allow`/`deny`/`ask` per call. Destructive
tools always require interactive confirmation by default. The CLI
prompts; the daemon currently grants all `ask` calls (a future version
can route them back to the connected client).

### `sessions/session.py`

A `Session` is `{id, messages, created_at, metadata}`, persisted as
JSON. The daemon uses the same `Session.load()` / `Session.save()` that
the in-process CLI does.

### `platform/`

OS abstractions for shell, process, and filesystem. Windows
`ProcessManager` returns structured `UnsupportedPlatform` errors.

## V3+ paths (still no rewrite needed)

| V3+ feature              | Hook                                        |
|--------------------------|---------------------------------------------|
| Mobile client            | WebSocket protocol already documented       |
| Voice client             | Same protocol; push transcribed text into `run` |
| Persistent PTY shell     | swap `platform.shell.make_shell` factory    |
| Real Windows processes   | add `platform/windows/...` and update the factory |
| Routing ask decisions    | extend `_run_session` to forward ask events |
| Plugin marketplace       | dynamic Tool loading via the registry       |
| Sandboxing               | wrap `Tool.run` in a sandboxed executor     |
| Remote daemon            | add auth layer; WebSocket protocol unchanged|
| Multi-tenant daemon      | namespace sessions per client token         |

All of these only add code. Nothing in the V1/V2 core needs to change.
