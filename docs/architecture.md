# Hyusk Architecture

This document describes the major interfaces and boundaries in Hyusk V1.
It explains the shape of the codebase so that V2 features (voice, mobile,
remote, daemon, additional providers) can land without rewriting the core.

## Goals

The V1 architecture serves three product goals:

1. A clean local CLI agent today (no daemon required).
2. A core that does not depend on any single model provider.
3. A core that does not depend on any single OS, but has explicit platform
   abstractions so additional platforms are additive.

A future V2 will add a daemon and remote clients. Those features do not
need to change the V1 interfaces — they only need new transports that
plug into the same event stream, tool registry, and session store.

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
                │  LLM Provider (abstr)│
                └─────────┬───────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   CLI (V1)        Voice (V2)        Mobile (V2)
                                       WebSocket (V2)
                                       Coding-agent (V2)

        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   Shell Tool       FS / Process / Git     New tools (V2)
        │
        ▼
   Platform layer: macOS / Linux / Windows
```

Everything below the dashed line — the **core** — is what V1 ships. The
clients above it (V1: CLI only) are kept thin: they parse input, render
events, and call into the core.

## Core modules

### `core/errors.py` — typed error hierarchy

All Hyusk-specific exceptions inherit from `HyuskError`. The agent catches
them and translates them into either tool-result error dicts (so the LLM
can recover) or friendly CLI messages. Generic `Exception` is **never**
silently swallowed.

| Error                | When                                           |
|----------------------|------------------------------------------------|
| `ToolNotFound`       | Tool name is not registered.                   |
| `PermissionDenied`   | Policy refuses a tool call.                    |
| `CommandFailed`      | Shell command exited non-zero.                 |
| `Timeout`            | Operation exceeded its timeout.                |
| `UnsupportedPlatform`| Feature not implemented on this OS.            |
| `FileNotFound`       | Filesystem operation on a missing path.        |
| `InvalidInput`       | Tool input failed validation.                  |
| `ProviderError`      | LLM provider returned an unrecoverable error.  |
| `AgentLoopLimit`     | Agent exceeded `max_iterations`.               |

### `core/logging.py` — structured logging

A `SecretFilter` scrubs common secret names (`api_key`, `token`,
`authorization`, etc.) from log messages and arguments. API keys are
never logged. `configure_logging()` is idempotent so the CLI can call it
multiple times safely.

### `events/` — typed event bus

`EventBus` is a synchronous pub/sub. Subscribers are plain callables.
The CLI subscribes once per session and reacts to `EventType` values:

```
AGENT_STARTED, AGENT_THINKING, AGENT_TEXT,
AGENT_TOOL_CALL, TOOL_STARTED, TOOL_OUTPUT, TOOL_COMPLETED,
AGENT_COMPLETED, AGENT_ERROR,
PROCESS_STARTED, PROCESS_EXITED
```

V2 clients (WebSocket, mobile) subscribe to the same events; the agent
emits nothing that only the CLI knows about.

### `llm/provider.py` — LLM abstraction

```python
class LLMProvider(abc.ABC):
    name: str
    def chat(self, messages, tools=None, *, model=None, temperature=None) -> LLMResponse: ...
```

`LLMResponse` carries a `text` field and a list of `ToolCallRequest`s.
The agent depends on this interface only. V1 ships an OpenAI-compatible
HTTP implementation (`llm/openai_compat.py`) that works with OpenAI,
OpenRouter, Together, Groq, LM Studio, llama.cpp, etc. Adding Anthropic,
Gemini, or a local llama.cpp server is a new file under `llm/` plus a
branch in `cli/app.py:build_provider()`.

### `tools/` — tool abstraction

A `Tool` is a small data record: name, description, JSON-schema-like
input, permission category, and an `execute()` callable. Tools are
**discovered** through `ToolRegistry`, never hardcoded.

Categories:

- `READ` — observation; auto-allowed by default.
- `WRITE` — modifies user files; can be denied by policy.
- `EXECUTE` — runs commands.
- `DESTRUCTIVE` — requires interactive confirmation by default
  (e.g. `kill_process`).

V1 ships: `list_directory`, `read_file`, `write_file`, `shell.execute`,
`list_processes`, `kill_process`, `git.status`, `git.diff`, `git.log`,
`git.branch`.

Adding a tool is a single new file and a one-line registration.

### `permissions/policy.py` — permission policy

A small rule engine:

```python
@dataclass
class PermissionPolicy:
    deny_categories: list[str]
    require_prompt: list[str]
    allow_tools: list[str]
    auto_allow_categories: list[str]
```

It produces a `Decision` per call (`allow`, `deny`, `ask`). The agent
honors `ask` by calling a `GrantCallback` supplied by the host. The CLI
prompts; a daemon would prompt the connected client.

Future policies (`yolo`, `paranoid`, `tiered`) live in this file only.

### `sessions/session.py` — session model

A `Session` is `{id, messages, created_at, metadata}`. It is persisted as
JSON under the user-config directory. The CLI creates a new one on each
launch and saves after every agent turn. `--session <id>` resumes one.

V2 mobile clients will rely on this exact shape to resume conversations
that began on another device.

### `agent/loop.py` — the agent loop

```
user input → messages
       ↓
       tool_specs = registry.all() as ToolSpec list
       ↓
       while iterations < max_iterations:
           response = llm.chat(messages, tools=tool_specs)
           if response.text: emit AGENT_TEXT
           if not response.wants_tool: break
           messages.append(assistant message with tool_calls)
           for tc in response.tool_calls:
               decision = policy.decide(tool)
               if deny → tool-result error → continue
               if ask and not granted → tool-result error → continue
               emit TOOL_STARTED
               tool_result = tool.run(arguments)
               emit TOOL_COMPLETED
               messages.append(tool result message)
       ↓
       return AgentResult(text, iterations, messages)
```

Safeguards:
- `max_iterations` (default 25, configurable).
- Tool errors are returned to the LLM as structured dicts, so a transient
  failure does not abort the loop.
- Permissions are checked **before** tool execution, never after.
- `AgentLoopLimit` is raised only when the loop ran out of iterations
  without producing a final answer.

### `cli/app.py` and `cli/repl.py`

- `app.py`: argparse wiring, builds provider/registry/policy/agent,
  handles one-shot and REPL entry points.
- `repl.py`: renders events to the terminal. It subscribes to the event
  bus and prints `AGENT_TEXT` deltas, framed `TOOL_STARTED` blocks, and
  timing/error lines for `TOOL_COMPLETED`. The agent **never** prints to
  stdout directly.

### `platform/`

- `shell.py`: stateless subprocess-based executor with structured result.
  Designed so a PTY-backed `Shell` can replace it later.
- `process.py`: `ProcessManager` interface with `PosixProcessManager`
  (`ps -axo`) and `WindowsProcessManager` (returns
  `UnsupportedPlatform` for V1).
- `filesystem.py`: pure utilities used by the filesystem tools.

The split between `platform/` and `tools/` is deliberate: `platform/`
holds OS abstractions that have nothing to do with the agent; `tools/`
binds those abstractions into LLM-callable tools.

### `config/`

Loads from (in order): env vars, `~/.config/hyusk/config.toml`,
defaults. Never reads `.env` files in the project tree.

## V2 paths (no rewrite needed)

| V2 feature           | Hook to use                                            |
|----------------------|--------------------------------------------------------|
| WebSocket / mobile client | subscribe to `events.events.EventBus`               |
| Voice client         | subscribe to `EventBus`, send user input to `Agent.run` |
| Persistent PTY shell | swap `platform.shell.make_shell` implementation         |
| Windows process support | add `platform/windows/...` and update `make_process_manager` |
| Anthropic provider   | add `llm/anthropic.py`, branch in `cli.app.build_provider` |
| Sandboxing           | wrap `Tool.run` in a sandboxed executor                |
| Daemon mode          | expose `agent.run()` over a transport, reuse everything else |

The shape of these hooks is the same as V1 — they only add code; they
do not change existing code.
