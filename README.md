# Hyusk

> A small, clean, extensible foundation for a cross-platform **computer agent**.

Hyusk is a local CLI agent that can run shell commands, read and write files,
inspect processes, and inspect git repositories — through natural language. V2
adds a long-running daemon and a WebSocket transport so future mobile, voice,
and remote clients can plug into the same core without touching it.

---

## What is new in V2

- **`hyusk daemon start|stop|status`** — long-running local daemon hosting
  the agent, sessions, and event stream.
- **WebSocket transport** — the daemon speaks a small JSON protocol. The CLI
  is a thin client that connects to the daemon when one is running, and
  falls back to an in-process agent when not.
- **Streaming LLM responses** — both the OpenAI-compatible and Anthropic
  providers emit incremental text deltas; the CLI renders them as they
  arrive.
- **Anthropic provider** — `HYUSK_LLM_PROVIDER=anthropic` to use the
  Anthropic Messages API.
- **53 tests passing**, including end-to-end WebSocket daemon tests with a
  fake LLM provider.

## What it does today (V2)

- Interactive REPL and one-shot commands.
- LLM-driven tool calling (OpenAI-compatible or Anthropic).
- Streaming responses (real SSE for both providers).
- Filesystem tools (`list_directory`, `read_file`, `write_file`) with safe
  defaults.
- Shell tool with timeout, structured stdout/stderr/exit/duration results.
- Process tools (`list_processes`, `kill_process`).
- Git tools (`git.status`, `git.diff`, `git.log`, `git.branch`).
- Pluggable permission policy; destructive tools always require
  interactive confirmation by default.
- Sessions are persisted as JSON and can be resumed.
- Lightweight typed event bus — the same bus is exposed over WebSocket.
- Structured logging with secret-scrubbing.
- Daemon with `start|stop|status` lifecycle and pid file.

## What is **not** built yet (V2 still does not ship these)

V2 still does **not** ship these — the interfaces are designed so they
land without rewriting the core:

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

Or, as a pip-installable package:

```bash
pip install hyusk
```

---

## Configuration

Loaded from (in order): environment variables prefixed with `HYUSK_`, a
TOML config file in the platform user-config dir, then built-in defaults.

| Variable                | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `HYUSK_LLM_PROVIDER`    | `openai` (default) or `anthropic`             |
| `HYUSK_LLM_MODEL`       | model name (e.g. `gpt-4o-mini`, `claude-3-5-sonnet-latest`) |
| `HYUSK_LLM_API_KEY`     | API key                                       |
| `HYUSK_LLM_BASE_URL`    | OpenAI-compatible base URL                    |
| `HYUSK_LLM_STREAM`      | `1`/`true` (default) to stream responses     |
| `OPENAI_API_KEY`        | fallback for the API key                      |
| `ANTHROPIC_API_KEY`     | fallback for the API key                      |
| `HYUSK_DAEMON_HOST`     | daemon bind host (default `127.0.0.1`)        |
| `HYUSK_DAEMON_PORT`     | daemon port (default `8765`)                  |
| `HYUSK_LOG_LEVEL`       | `DEBUG`/`INFO`/`WARNING`/`ERROR`              |

Example `config.toml` at the platform user-config dir:

```toml
[llm]
provider = "anthropic"     # or "openai"
model = "claude-3-5-sonnet-latest"
api_key = "sk-..."         # prefer env var

[agent]
max_iterations = 25

[daemon]
host = "127.0.0.1"
port = 8765

[permissions]
require_prompt = ["kill_process"]
```

API keys are never logged (a `SecretFilter` strips common key names).

---

## Usage

### Start the daemon (optional but recommended)

```bash
hyusk --daemon-action start      # foreground
hyusk --daemon-action status     # is it running?
hyusk --daemon-action stop       # stop it
```

Once the daemon is running, every `hyusk` command — REPL, one-shot, or
session list — uses the daemon transparently. If the daemon is not
running, the CLI starts an in-process agent (V1 behavior).

### One-shot

```bash
hyusk "show me the processes using the most CPU"
hyusk "what is in README.md?"
hyusk "summarize recent git history"
hyusk --no-daemon "..."        # force in-process agent
hyusk --daemon-only "..."      # fail if daemon is unreachable
```

### Interactive REPL

```bash
$ hyusk
hyusk v0.2.0  (connected to daemon at 127.0.0.1:8765)
(type 'exit' or Ctrl-D to quit, 'help' for commands)
hyusk > list the files in this directory

-> list_directory
   path: .
   ok (12 ms)

Here are the contents...

hyusk > tools
available tools (resolved from server):
  - list_directory, read_file, write_file
  - shell.execute, list_processes, kill_process
  - git.status, git.diff, git.log, git.branch

hyusk > exit
```

### Sessions

```bash
hyusk --list-sessions         # queries the daemon if running
hyusk --session <id> "..."    # resume a session
```

### Useful flags

```bash
hyusk --model claude-3-5-sonnet-latest "..."
hyusk --no-confirm "..."      # auto-allow destructive tools (careful)
```

---

## Daemon protocol

V2 clients (and future mobile/voice clients) speak this JSON-over-WebSocket
protocol with the daemon:

```text
client -> server:
  {"type": "run", "session_id": "<id|new>", "input": "...", "model": "..."}
  {"type": "list_sessions"}
  {"type": "load_session", "id": "..."}
  {"type": "ping"}

server -> client:
  {"type": "event", "event": "agent.started|tool.started|...", "data": {...}}
  {"type": "done", "session_id": "...", "iterations": N, "text_chars": N}
  {"type": "error", "message": "..."}
  {"type": "sessions", "sessions": [...]}
  {"type": "session", "session": {"id":..., "messages":[...]}}
  {"type": "pong"}
```

There is no separate "streaming" message type — events already stream.
Text comes through `agent.text` with `delta: true` for partial chunks.

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
- `--no-confirm` bypasses prompts (subject to deny rules).
- Tool output is truncated at `agent.max_tool_output_bytes`.
- API keys are scrubbed from logs.

In V2, the **daemon does not prompt**: the local CLI is responsible for
prompting at the terminal. The daemon grants all `ask` calls (a future
version can route them back to the connected client).

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
├── README.md
├── LICENSE
├── docs/
│   └── architecture.md
├── src/hyusk/
│   ├── cli/        # argparse + REPL rendering + daemon subcommands
│   ├── agent/      # agent loop (streaming-aware)
│   ├── llm/        # provider abstraction + OpenAI-compat + Anthropic
│   ├── tools/      # tool base + registry + per-tool modules
│   ├── permissions/# permission policy
│   ├── sessions/   # session persistence
│   ├── events/     # event bus
│   ├── daemon/     # WebSocket server (V2)
│   ├── client/     # WebSocket client used by the CLI (V2)
│   ├── platform/   # OS abstractions (shell, process, filesystem)
│   ├── config/     # config loader (now includes daemon + stream)
│   └── core/       # errors, logging
└── tests/
```

### Adding a new tool

1. Implement a function returning a `Tool` (see `tools/filesystem/tools.py`).
2. Register it from `register_*_tools(registry)`.
3. Call the registrar in `daemon/registry_builder.py:build_registry()`.
4. Add a test under `tests/test_<area>.py`.

### Adding a new LLM provider

Implement `LLMProvider.chat()` and (optionally) `chat_stream()` in a new
file under `src/hyusk/llm/`. Then add a branch in
`daemon/registry_builder.py:build_provider()`.

---

## Roadmap (V3+)

- Voice client (subscribe to daemon over WebSocket, push transcribed audio).
- Mobile app (iOS/Android) talking to the daemon.
- Persistent PTY-backed shell sessions.
- Sandboxed tool execution.
- Browser automation as a new tool category.
- Plugin marketplace.
- Routing `ask` decisions from the daemon back to the connected client.

See [`docs/architecture.md`](docs/architecture.md) for the architecture
that makes these possible without rewriting the core.

---

## License

MIT. See [LICENSE](LICENSE).
