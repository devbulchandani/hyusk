# Hyusk

> A small, clean, extensible foundation for a cross-platform **computer agent**.

Hyusk is a local CLI agent that can run shell commands, read and write files,
inspect processes, and inspect git repositories — through natural language. It
is the V1 foundation for a future system that lets you control your Mac,
Windows, or Linux computer by voice, mobile app, or another agent.

The architecture is deliberately modular so future voice clients, phone apps,
remote clients, and coding-agent integrations can plug into the same core
without rewriting it.

---

## What it does today (V1)

- Interactive REPL and one-shot commands.
- LLM-driven tool calling (OpenAI-compatible provider by default).
- Filesystem tools (`list_directory`, `read_file`, `write_file`) with safe
  defaults: large files are truncated, missing files return structured
  errors.
- Shell tool with timeout, structured stdout/stderr/exit-code/duration
  results.
- Process tools (`list_processes`, `kill_process`) with a portable
  interface (Posix now; Windows returns structured unsupported errors).
- Git tools (`git.status`, `git.diff`, `git.log`, `git.branch`).
- Pluggable permission policy. Destructive tools require interactive
  confirmation by default.
- Sessions are persisted as JSON so a one-shot or REPL can be resumed.
- Lightweight typed event bus so future WebSocket / mobile clients can
  subscribe to the same stream the CLI renders.
- Structured logging with secret-scrubbing filters.
- 39 tests covering registry, shell, filesystem, permissions, agent loop,
  events, sessions, config, git, process, and logging.

## What it deliberately is **not** (yet)

V1 is a foundation. These are intentionally **not** built yet:

- Wake-word / voice transcription / text-to-speech.
- Mobile app, remote control, cloud backend.
- Screen / computer-vision automation.
- Browser automation, plugin marketplace.
- A daemon / WebSocket server.

The interfaces are designed so adding these later does not require rewriting
the core. See [`docs/architecture.md`](docs/architecture.md).

---

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
- An OpenAI-compatible API key (or a custom base URL pointing at any
  OpenAI-compatible server: OpenRouter, Together, Groq, LM Studio,
  llama.cpp, etc.)

`git` must be installed for the git tools (the shell and filesystem tools
work without it). On Linux/macOS, `ps` is used for process listing.

---

## Installation

```bash
# from source
git clone https://github.com/devbulchandani/hyusk
cd hyusk
uv sync --extra dev
uv run hyusk --help
```

Or as a pip-installable package (once published):

```bash
pip install hyusk
```

---

## Configuration

Configuration is read from (in order of precedence):

1. Environment variables prefixed with `HYUSK_`
2. A TOML file in the platform-specific user config directory
3. Built-in defaults

The user config directory is:

| Platform | Path                                                          |
|----------|---------------------------------------------------------------|
| macOS    | `~/Library/Application Support/hyusk/config.toml`             |
| Linux    | `${XDG_CONFIG_HOME:-~/.config}/hyusk/config.toml`             |
| Windows  | `%APPDATA%\hyusk\config.toml`                              |

Example `config.toml`:

```toml
[llm]
provider = "openai"             # or any openai-compatible target
model = "gpt-4o-mini"
api_key = "sk-..."              # prefer env var in practice
base_url = ""                   # e.g. "https://openrouter.ai/api/v1"

[agent]
max_iterations = 25
max_tool_output_bytes = 200000
max_file_read_bytes = 1000000

[permissions]
# Per-tool overrides. Categories: READ, WRITE, EXECUTE, DESTRUCTIVE.
policy = { "kill_process" = "DESTRUCTIVE" }
# Tools that always require interactive confirmation.
require_prompt = ["kill_process"]
```

Environment variables (preferred for secrets):

| Variable              | Purpose                                  |
|-----------------------|------------------------------------------|
| `HYUSK_LLM_PROVIDER`  | provider name (default `openai`)         |
| `HYUSK_LLM_MODEL`     | model name                               |
| `HYUSK_LLM_API_KEY`   | API key                                  |
| `HYUSK_LLM_BASE_URL`  | OpenAI-compatible base URL               |
| `OPENAI_API_KEY`      | fallback for the API key                  |
| `ANTHROPIC_API_KEY`   | fallback for the API key                  |
| `HYUSK_LOG_LEVEL`    | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

API keys are **never** logged: a `SecretFilter` strips common key names
from log records.

---

## Usage

### Interactive REPL

```bash
$ hyusk
hyusk v0.1.0  (type 'exit' or Ctrl-D to quit, 'help' for commands)
hyusk > list the files in this directory
hyusk is thinking...

┌─ list_directory
│ path: .
└────────────────────────
[ok in 12 ms]

I'll inspect the directory for you. Here are the contents...

hyusk > tools
available tools:
  - list_directory (READ)
  - read_file (READ)
  - write_file (WRITE)
  - shell.execute (EXECUTE)
  - list_processes (READ)
  - kill_process (DESTRUCTIVE)
  - git.status (READ)
  - git.diff (READ)
  - git.log (READ)
  - git.branch (READ)

hyusk > exit
```

### One-shot

```bash
hyusk "show me the processes using the most CPU"
hyusk "what's in README.md?"
hyusk "summarize recent git history"
```

### List / resume sessions

```bash
hyusk --list-sessions
hyusk --session <id> "continue from where we left off"
```

### Useful flags

```bash
hyusk --no-confirm "..."     # auto-allow destructive tools (use carefully)
hyusk --model gpt-4o "..."    # override the configured model
```

---

## Available tools

| Tool              | Category    | Description                                          |
|-------------------|-------------|------------------------------------------------------|
| `list_directory`  | READ        | List directory entries with size and mtime.          |
| `read_file`       | READ        | Read a UTF-8 text file; truncates very large files.  |
| `write_file`      | WRITE       | Write a UTF-8 text file; creates parents.            |
| `shell.execute`   | EXECUTE     | Run a shell command. Returns stdout/stderr/exit/duration. |
| `list_processes`  | READ        | List processes, sortable by cpu/mem/pid/time.        |
| `kill_process`    | DESTRUCTIVE | Send TERM/KILL/INT/HUP to a PID.                     |
| `git.status`      | READ        | Porcelain git status with branch line.               |
| `git.diff`        | READ        | Git diff (optionally staged).                        |
| `git.log`         | READ        | Recent commits.                                      |
| `git.branch`      | READ        | Current branch.                                      |

---

## Security model

- All tools declare a **permission category** (`READ`, `WRITE`, `EXECUTE`,
  `DESTRUCTIVE`).
- A `PermissionPolicy` decides per call: `allow`, `deny`, or `ask`.
- Destructive tools **always** require interactive confirmation by default.
- In non-interactive contexts (no TTY), `kill_process` is **refused** rather
  than silently auto-allowed.
- `--no-confirm` bypasses interactive prompts (still subject to deny rules).
- Shell output is capped; tool output is truncated at
  `agent.max_tool_output_bytes` so the LLM cannot accidentally ingest a
  multi-gigabyte log.

Future versions will support finer-grained policies (per-command allow
lists, sandboxed execution, etc.) without changing tool code.

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
│   ├── cli/        # argparse, REPL, rendering
│   ├── agent/      # agent loop
│   ├── llm/        # provider abstraction + OpenAI-compat
│   ├── tools/      # tool base + registry + per-tool modules
│   ├── permissions/# permission policy
│   ├── sessions/   # session persistence
│   ├── events/     # event bus
│   ├── platform/   # OS abstractions (shell, process, filesystem)
│   ├── config/     # config loader
│   └── core/       # errors, logging
└── tests/
```

### Adding a new tool

1. Implement a function returning a `Tool` (see
   `src/hyusk/tools/filesystem/tools.py`).
2. Register it from `register_*_tools(registry)` in that module.
3. Call the registrar in `cli/app.py:build_registry()`.
4. Add a test under `tests/test_<area>.py`.

### Adding a new LLM provider

Implement `LLMProvider.chat()` in a new file under `src/hyusk/llm/`, then
add a branch in `cli/app.py:build_provider()`. The agent loop does not need
to change.

---

## Roadmap

- Voice / mobile / WebSocket clients (speak to the same daemon).
- Anthropic-native provider.
- Persistent PTY-backed shell sessions.
- Sandboxed tool execution.
- Browser automation as an additional tool category.
- Plugin marketplace.

See [`docs/architecture.md`](docs/architecture.md) for the architecture
that makes these possible without rewriting the core.

---

## License

MIT. See [LICENSE](LICENSE).
