# Hyusk

> A small, clean, extensible foundation for a cross-platform **computer agent**.

Hyusk is a local CLI agent that can run shell commands, read and write files,
inspect processes, and inspect git repositories — through natural language. V4
adds **persistent task state**, a **voice client**, **session compaction**, and
a **plugin system**, so the daemon survives restarts and the agent core can be
extended without forking the project.

The architecture is modular so future voice clients, phone apps, remote
clients, and coding-agent integrations plug into the same core without
touching it.

---

## What is new in V4 (and V4.1)

- **Persistent task state.** Tasks are written to disk; on restart the
  daemon marks any that were running as `interrupted` so the user can
  inspect or discard them.
- **Session compaction.** `compact_session` asks the LLM to summarize a
  long session and returns a new (smaller) session id. Keeps the LLM
  context window manageable.
- **Voice client.** A standalone `hyusk voice` subcommand that reads
  from stdin (text mode) or the microphone (with `sounddevice`) and
  feeds the daemon. The same WebSocket protocol — just a different
  process.
- **Plugin discovery.** Drop Python files in `~/.config/hyusk/plugins/`
  with a `register(registry)` function; the daemon loads them on
  startup.
- **V4.1: `hyusk config` subcommand.** Set the API key, model, provider,
  and base URL from the CLI — no env vars required. Use any OpenAI-
  compatible endpoint (OpenRouter, Together, Groq, LM Studio).
- **V4.1: Per-invocation overrides.** `--provider`, `--model`,
  `--api-key`, `--base-url` flags override the config for one run.
- **V4.1: Real TTS.** The voice client speaks replies. Default on
  macOS is the built-in `say` command. Optional: KittenTTS (local,
  open-weights), OpenAI TTS (cloud).
- **V4.1: Real STT.** The voice client's mic mode transcribes via
  mlx-whisper (Apple Silicon), openai-whisper (other), or the
  OpenAI Whisper API. Falls back to text mode if none are available.
- **Protocol v4 handshake.** `{"type": "version"}` returns the
  protocol number so clients can adapt.
- **87 tests passing**, including persistent-task, plugin, and TTS
  backend tests.

## What V1, V2, and V3 already shipped

- Interactive REPL and one-shot commands.
- OpenAI-compatible and Anthropic providers (both stream SSE).
- Filesystem, shell, process, and git tools.
- Pluggable permission policy; destructive tools require confirmation.
- JSON-persisted sessions that can be resumed.
- Typed event bus.
- Long-running daemon with `start|stop|status` and a pid file.
- WebSocket protocol with concurrent tasks, steering, cancellation, and
  ask routing.

## What is **not** built yet

V4 does **not** ship these — the interfaces are designed so they land
without rewriting the core:

- Voice / mobile / WebSocket clients beyond the standalone `hyusk voice` CLI.
- Real-time wake-word detection.
- Cloud backend, multi-tenant daemon.
- Screen / computer-vision automation.
- Browser automation, plugin marketplace.
- Streaming mid-stream cancellation.

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

Loaded from (in order): `HYUSK_CONFIG_DIR` (override), env vars prefixed with
`HYUSK_`, a TOML file in the user-config dir, then built-in defaults.

| Variable                | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `HYUSK_CONFIG_DIR`       | Override the user-config dir (for tests).     |
| `HYUSK_LLM_PROVIDER`    | `openai` (default) or `anthropic`             |
| `HYUSK_LLM_MODEL`       | model name                                    |
| `HYUSK_LLM_API_KEY`     | API key                                       |
| `HYUSK_LLM_BASE_URL`    | OpenAI-compatible base URL                    |
| `HYUSK_LLM_STREAM`      | `1`/`true` (default) to stream responses     |
| `HYUSK_DAEMON_HOST`     | daemon bind host (default `127.0.0.1`)        |
| `HYUSK_DAEMON_PORT`     | daemon port (default `8765`)                  |
| `HYUSK_LOG_LEVEL`       | `DEBUG`/`INFO`/`WARNING`/`ERROR`              |

API keys are never logged.

User config directory:
- macOS: `~/Library/Application Support/hyusk/`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/hyusk/`
- Override with `HYUSK_CONFIG_DIR=...`

---

## Set up the API key

No environment variables are required. Use `hyusk config`:

```bash
# OpenAI
hyusk config set llm.provider openai
hyusk config set llm.api_key sk-...
hyusk config set llm.model gpt-4o-mini

# Anthropic
hyusk config set llm.provider anthropic
hyusk config set llm.api_key sk-ant-...
hyusk config set llm.model claude-3-5-sonnet-latest

# OpenRouter (or any OpenAI-compatible endpoint)
hyusk config set llm.provider openai
hyusk config set llm.api_key sk-or-v1-...
hyusk config set llm.base_url https://openrouter.ai/api/v1
hyusk config set llm.model anthropic/claude-3.5-sonnet

# Show the active config (api keys masked)
hyusk config show

# One-off override without changing the saved config
hyusk --provider anthropic --api-key sk-ant-... --model claude-3-5-sonnet-latest "..."
```

The config file lives at:
- macOS: `~/Library/Application Support/hyusk/config.toml`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/hyusk/config.toml`
- Override with `HYUSK_CONFIG_DIR=...`

---

## Usage

### Start the daemon

```bash
hyusk --daemon-action start
hyusk --daemon-action status
hyusk --daemon-action stop
```

### One-shot and REPL (V3 features)

```bash
hyusk "what is in README.md?"
hyusk --daemon-only "..."

# REPL: bg: prompts, steer, cancel, tasks
hyusk
```

### Voice client (V4)

```bash
# Text mode (stdin → daemon)
hyusk --voice --text

# Mic mode (requires sounddevice + an STT engine; the default is a stub)
hyusk --voice --mic
```

The voice client uses the same WebSocket protocol as the regular CLI. It's a
demonstration that the V2/V3 protocol works across process boundaries.

### Plugins (V4)

Drop a Python file in `~/.config/hyusk/plugins/`:

```python
# ~/.config/hyusk/plugins/hello.py
from hyusk.tools.base import Tool, READ

def register(registry):
    registry.register(Tool(
        name="hello",
        description="Say hello to the given name.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        permission=READ,
        execute=lambda a: {"greeting": f"hello, {a['name']}"},
    ))
```

On daemon startup, the file is imported and `register(registry)` is called.
A broken plugin is logged and skipped — it cannot prevent the daemon from
starting.

### Sessions

```bash
hyusk --list-sessions
hyusk --session <id> "..."
```

### Sessions (V4: compaction)

When a session grows large, ask the daemon to compact it:

```
client -> server: {"type": "compact_session", "session_id": "<id>"}
server -> client: {"type": "compacted", "session_id": "<old>", "new_session_id": "<new>"}
```

The daemon asks the LLM to summarize the conversation and writes a new
session that contains the summary.

---

## Daemon protocol (V4)

The V4 protocol is a superset of V3. New messages:

```text
client -> server:
  {"type": "version"}
  {"type": "task_detail", "task_id": "..."}
  {"type": "list_tasks_all"}
  {"type": "compact_session", "session_id": "..."}
  {"type": "discard_task", "task_id": "..."}

server -> client:
  {"type": "version", "version": "0.4.0", "protocol": 4}
  {"type": "task_detail", "task": {...}}
  {"type": "tasks", "tasks": [...]}                # in response to list_tasks_all
  {"type": "compacted", "session_id": "...", "new_session_id": "..."}
  {"type": "discarded", "task_id": "..."}
```

Persistent tasks are written to `<user_config>/hyusk/tasks/<id>.json` so
they survive daemon restarts. Running tasks at restart are marked
`interrupted` (the agent thread is gone; the user inspects them with
`task_detail` and discards or resumes via a new `run`).

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

User plugins (see above) can add more.

---

## Security model

- Tools declare a **permission category** (`READ`, `WRITE`, `EXECUTE`,
  `DESTRUCTIVE`).
- `PermissionPolicy` decides per call: `allow`, `deny`, or `ask`.
- Destructive tools always require interactive confirmation by default.
- The daemon routes `ask` to the connected client. The CLI prompts; a
  future mobile/voice client implements its own prompt.
- API keys are scrubbed from logs.

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
│   ├── agent/      # loop (streaming + steering), TaskManager, TaskStore
│   ├── llm/        # provider abstraction + OpenAI-compat + Anthropic
│   ├── tools/      # tool base + registry + per-tool modules
│   ├── permissions/# permission policy
│   ├── sessions/   # session persistence + SessionStore
│   ├── events/     # event bus
│   ├── daemon/     # WebSocket server (V4: persistent tasks, ask routing, plugin loader)
│   ├── client/     # WebSocket client (V4: version, task_detail, compact_session, …)
│   ├── platform/   # OS abstractions
│   ├── plugins/    # V4: user plugin discovery
│   ├── voice/      # V4: standalone voice client
│   ├── config/     # config loader (V4: HYUSK_CONFIG_DIR)
│   └── core/       # errors, logging
└── tests/
```

### Adding a new tool

1. Implement a function returning a `Tool` (see `tools/filesystem/tools.py`).
2. Register it from `register_*_tools(registry)`.
3. Call the registrar in `daemon/registry_builder.py:build_registry()`.

### Adding a new LLM provider

Implement `LLMProvider.chat()` and (optionally) `chat_stream()` in a new
file under `src/hyusk/llm/`. Add a branch in
`daemon/registry_builder.py:build_provider()`.

### Writing a plugin

Drop a `.py` file in `~/.config/hyusk/plugins/` with a top-level
`register(registry)` function. See the example above.

---

## Roadmap (V5+)

- Mobile client app (iOS/Android) talking to the daemon.
- Persistent PTY-backed shell sessions.
- Sandboxed tool execution.
- Browser automation as a new tool category.
- Streaming mid-stream cancellation.
- Plugin marketplace (curated list of community plugins).

See [`docs/architecture.md`](docs/architecture.md).

---

## License

MIT. See [LICENSE](LICENSE).
