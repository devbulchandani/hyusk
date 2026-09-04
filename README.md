# Hyusk

> A small, clean, extensible foundation for a cross-platform **computer agent**.

Hyusk is a local CLI agent that can run shell commands, read and write files,
inspect processes, and inspect git repositories — through natural language. V3
adds **concurrent agent tasks with steering and cancellation** so you can
fire off a long-running job and keep talking to Hyusk while it works.

The architecture is modular so future voice clients, phone apps, remote
clients, and coding-agent integrations can plug into the same core without
touching it.

---

## What is new in V3

- **Concurrent agent runs.** Every `run` returns a `task_id` immediately.
  Multiple tasks execute in parallel. The CLI multiplexes events from all
  running tasks.
- **Steering (`steer <id> <message>`).** Inject a follow-up user message
  into a running task. The agent picks it up between tool calls.
- **Cancellation (`cancel <id>`).** Stop a running task cleanly. The current
  tool call finishes, then the agent loop exits.
- **Background mode (`bg: <prompt>`).** Start a task without waiting for
  it; keep chatting in the foreground.
- **ask routing.** The daemon no longer auto-grants destructive tool calls.
  It forwards `ask` decisions to the client that started the task. The CLI
  prompts; a future mobile client can implement its own prompt.
- **60 tests passing**, including concurrent-task and steering coverage.

## What V1 and V2 already shipped

- Interactive REPL and one-shot commands.
- OpenAI-compatible and Anthropic providers (both stream SSE).
- Filesystem, shell, process, and git tools.
- Pluggable permission policy; destructive tools require confirmation.
- JSON-persisted sessions that can be resumed.
- Typed event bus (the same bus is exposed over WebSocket).
- Long-running daemon with `start|stop|status` and a pid file.

## What is **not** built yet

V3 does **not** ship these — the interfaces are designed so they land
without rewriting the core:

- Wake-word / voice transcription / text-to-speech.
- Mobile app, remote control, cloud backend.
- Screen / computer-vision automation.
- Browser automation, plugin marketplace.

---

## Requirements

- Python 3.11+
- `uv` (recommended) or `pip`
- An OpenAI-compatible **or** Anthropic API key.

`git` must be installed for the git tools. On Linux/macOS, `ps` is used for
process listing.

---

## Installation

```bash
git clone https://github.com/devbulchandani/hyusk
cd hyusk
uv sync --extra dev
uv run hyusk --help
```

---

## Configuration

Loaded from (in order): env vars prefixed with `HYUSK_`, a TOML file in
the platform user-config dir, then built-in defaults.

| Variable                | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `HYUSK_LLM_PROVIDER`    | `openai` (default) or `anthropic`             |
| `HYUSK_LLM_MODEL`       | model name                                    |
| `HYUSK_LLM_API_KEY`     | API key                                       |
| `HYUSK_LLM_BASE_URL`    | OpenAI-compatible base URL                    |
| `HYUSK_LLM_STREAM`      | `1`/`true` (default) to stream responses     |
| `HYUSK_DAEMON_HOST`     | daemon bind host (default `127.0.0.1`)        |
| `HYUSK_DAEMON_PORT`     | daemon port (default `8765`)                  |
| `HYUSK_LOG_LEVEL`       | `DEBUG`/`INFO`/`WARNING`/`ERROR`              |

API keys are never logged.

---

## Usage

### Start the daemon (recommended)

```bash
hyusk --daemon-action start
hyusk --daemon-action status
hyusk --daemon-action stop
```

When the daemon is running, every `hyusk` command — REPL, one-shot, or
session list — uses it transparently. If not, the CLI starts an in-process
agent (V1 behavior).

### One-shot

```bash
hyusk "show me the processes using the most CPU"
hyusk "what is in README.md?"
hyusk --no-daemon "..."        # force in-process agent
hyusk --daemon-only "..."      # fail if daemon is unreachable
```

### Interactive REPL — concurrent tasks

```bash
$ hyusk
hyusk v0.3.0  (connected to daemon at 127.0.0.1:8765)
(type 'help' for commands)
hyusk > bg: count files in /usr/local recursively

[abcd1234] started task abcd1234 (session ...)
hyusk > list the files in this directory instead

[efgh5678] -> list_directory
   path: .
   ok (12 ms)

Here are the contents...

hyusk > tasks
  abcd1234  running  iter=2  'count files in /usr/local recursively'
  efgh5678  done     iter=1  'list the files in this directory instead'

hyusk > steer abcd1234 skip node_modules
[abcd1234] [steer] skip node_modules

hyusk > cancel efgh5678
cancel: efgh5678 ok=True

hyusk > help
commands:
  bg: <prompt>            start a background task
  steer <id> <message>    inject a follow-up message into a running task
  cancel <id>             cancel a running task
  tasks                   list tasks (active + recent)
  session                 show the current session id
  reset                   next prompt starts a new session
  tools                   list available tools
  help                    show this list
  exit | quit | :q        leave the REPL
```

### Sessions

```bash
hyusk --list-sessions
hyusk --session <id> "..."    # resume
```

---

## Daemon protocol (V3)

```text
client -> server:
  {"type": "run", "session_id": "<id|new>", "input": "...", "model": "..."}
  {"type": "list_sessions"}
  {"type": "list_tasks"}
  {"type": "cancel", "task_id": "..."}
  {"type": "steer", "task_id": "...", "input": "..."}
  {"type": "grant", "ask_id": "...", "granted": bool}
  {"type": "ping"}

server -> client:
  {"type": "task", "task_id": "...", "session_id": "..."}
  {"type": "event", "task_id": "...", "session_id": "...",
                 "event": "agent.started|tool.started|...", "data": {...}}
  {"type": "ask", "ask_id": "...", "task_id": "...", "tool": "...",
                 "arguments": {...}}
  {"type": "task_done", "task_id": "...", "state": "done|cancelled|errored",
                    "iterations": N, "cancelled": bool, "error": "..."}
  {"type": "error", "message": "..."}
  {"type": "pong"}
  {"type": "sessions", "sessions": [...]}
  {"type": "tasks", "tasks": [...]}
```

Multiple tasks can run at once; every event is tagged with `task_id` so
the client can multiplex.

---

## Available tools

| Tool              | Category    | Description                                          |
|-------------------|-------------|------------------------------------------------------|
| `list_directory`  | READ        | List directory entries.                              |
| `read_file`       | READ        | Read a UTF-8 text file; truncates large files.       |
| `write_file`      | WRITE       | Write a UTF-8 text file; creates parents.            |
| `shell.execute`   | EXECUTE     | Run a shell command.                                 |
| `list_processes`  | READ        | List processes, sortable by cpu/mem/pid/time.        |
| `kill_process`    | DESTRUCTIVE | Send TERM/KILL/INT/HUP to a PID.                     |
| `git.status`      | READ        | Porcelain git status with branch line.               |
| `git.diff`        | READ        | Git diff (optionally staged).                        |
| `git.log`         | READ        | Recent commits.                                      |
| `git.branch`      | READ        | Current branch.                                      |

---

## Security model

- Tools declare a **permission category** (`READ`, `WRITE`, `EXECUTE`,
  `DESTRUCTIVE`).
- `PermissionPolicy` decides per call: `allow`, `deny`, or `ask`.
- Destructive tools always require interactive confirmation by default.
- In non-interactive contexts, `kill_process` is **refused** rather than
  silently auto-allowed.
- `--no-confirm` bypasses prompts (still subject to deny rules).
- API keys are scrubbed from logs.

When the daemon is running, the **client that started a task** is the one
that gets the `ask` message. The CLI prompts; a future mobile/voice
client implements its own prompt.

---

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run mypy src/hyusk
```

### Project structure

```
hyusk/
├── README.md, LICENSE, .gitignore, pyproject.toml
├── docs/architecture.md
├── src/hyusk/
│   ├── cli/        # argparse, REPL, daemon subcommands
│   ├── agent/      # agent loop (streaming + steering) and TaskManager
│   ├── llm/        # provider abstraction + OpenAI-compat + Anthropic
│   ├── tools/      # tool base + registry + per-tool modules
│   ├── permissions/# permission policy
│   ├── sessions/   # session persistence + SessionStore
│   ├── events/     # event bus
│   ├── daemon/     # WebSocket server (concurrent tasks V3)
│   ├── client/     # WebSocket client (V3: submit/cancel/steer/list_tasks)
│   ├── platform/   # OS abstractions
│   ├── config/     # config loader
│   └── core/       # errors, logging
└── tests/
```

### Adding a new tool

1. Implement a function returning a `Tool` (see `tools/filesystem/tools.py`).
2. Register it from `register_*_tools(registry)`.
3. Call the registrar in `daemon/registry_builder.py:build_registry()`.

### Adding a new LLM provider

Implement `LLMProvider.chat()` and (optionally) `chat_stream()` in a new
file under `src/hyusk/llm/`. Then add a branch in
`daemon/registry_builder.py:build_provider()`.

---

## Roadmap (V4+)

- Voice / mobile clients (subscribe to the daemon over WebSocket).
- Persistent PTY-backed shell sessions.
- Sandboxed tool execution.
- Browser automation as a new tool category.
- Plugin marketplace.

See [`docs/architecture.md`](docs/architecture.md).

---

## License

MIT. See [LICENSE](LICENSE).
