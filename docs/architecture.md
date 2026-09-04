# Hyusk Architecture

This document describes the major interfaces and boundaries in Hyusk V4.
V1 laid out the core. V2 layered a daemon + WebSocket transport and
streaming. V3 added concurrent agent tasks with steering and
cancellation. V4 adds **persistent state**, a **voice client**,
**session compaction**, and a **plugin system**.

## Goals

1. A clean local CLI agent today (no daemon required).
2. A core that does not depend on any single model provider.
3. A core that does not depend on any single OS, but has explicit
   platform abstractions so additional platforms are additive.
4. The CLI is a thin client that talks to a long-running daemon.
5. Future clients (mobile, voice, remote, WebSocket) plug in without
   touching the core.
6. The agent loop is streaming-aware.
7. The user can run multiple tasks in parallel and steer them.
8. **V4:** task state survives daemon restarts. Sessions can be
   compacted. The agent core is extensible via user plugins. Voice
   clients work today.

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
                │  Plugin Loader (V4) │
                └─────────┬───────────┘
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
   CLI (V4)         Voice (V4)         Mobile (V5)
   WebSocket         WebSocket          WebSocket
   client             client             client
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   HYUSK DAEMON      │
                │   WebSocket server  │
                │   (V4: persistent   │
                │    tasks, ask      │
                │    routing,         │
                │    plugin loader)   │
                └─────────┬───────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │   TASK MANAGER      │
                │   + TASK STORE (V4) │
                │  Persists TaskInfo  │
                │  to disk; restore() │
                │  marks running      │
                │  tasks as           │
                │  INTERRUPTED.       │
                └─────────────────────┘
```

## V4 deltas

### `agent/tasks.py` — `TaskStore` + `TaskInfo` extensions + `INTERRUPTED`

- `TaskInfo` now carries an optional `transcript: list[dict]` of session
  messages for inspection after a restart.
- `TaskInfo.from_dict()` was added so records can be reloaded from disk.
- `TaskState.INTERRUPTED` is a new state for tasks that were running
  when the daemon was last killed.
- `TaskStore` is a new class in the same module. It writes each task's
  `TaskInfo` to `<user_config>/hyusk/tasks/<id>.json` on every state
  change.
- `TaskManager` now accepts an optional `store` argument. When set, it
  hooks into `Task._set_state()` and persists the latest snapshot
  after every state transition.
- `TaskManager.restore()` is called once at daemon startup. It loads
  every persisted task and marks any that were `RUNNING` or `PENDING`
  as `INTERRUPTED`, appending `[interrupted by daemon restart]` to
  the error message.
- The `_consume` method now updates `self.session.messages` **before**
  setting the final state, so any state-change callback (e.g. the
  `TaskStore.save`) sees the full transcript.

### `daemon/server.py` — V4 protocol

- New messages handled:
  - `{"type": "version"}` → `{"type": "version", "version": "0.4.0",
    "protocol": 4}`.
  - `{"type": "task_detail", "task_id": "..."}` → full `TaskInfo` from
    the `TaskStore`, including the transcript.
  - `{"type": "list_tasks_all"}` → union of in-memory + persisted
    tasks.
  - `{"type": "compact_session", "session_id": "..."}` → asks the LLM
    to summarize the session, writes a new session with the summary,
    returns `{"type": "compacted", "new_session_id": "..."}`. Falls back
    to a deterministic stub if the LLM is unreachable.
  - `{"type": "discard_task", "task_id": "..."}` → removes the persisted
    record. Does not affect the session.

### `client/client.py` — V4 client methods

- `DaemonClient.version()` — protocol handshake.
- `DaemonClient.task_detail(task_id)` — full task info.
- `DaemonClient.list_tasks_all()` — union of in-memory + persisted.
- `DaemonClient.compact_session(session_id)` — request compaction,
  return new session id.
- `DaemonClient.discard_task(task_id)` — drop a persisted record.

### `voice/client.py` — V4 voice client (NEW)

A standalone async CLI process that connects to the daemon via
`DaemonClient` and submits user input as `run` messages. Two modes:

- `--text`: read lines from stdin. Default; works in any environment.
- `--mic`: capture from the microphone. Falls back to a stub unless
  `sounddevice` is installed; STT is intentionally not bundled.

This demonstrates the V2/V3 protocol working across process
boundaries, and is the template a future mobile or web client can
follow.

### `plugins/loader.py` — V4 plugin discovery (NEW)

`load_plugins(registry, plugin_dir=...)` imports every `*.py` file in
the user plugin dir and calls its `register(registry)`. Used by the
daemon at startup and by the CLI's in-process agent as a fallback.
Broken plugins are logged and skipped.

### `config/config.py` — `user_config_dir` respects `HYUSK_CONFIG_DIR`

A new env var `HYUSK_CONFIG_DIR` overrides the platform-default
config dir. Useful for tests and for users who want to relocate the
config dir. On macOS and Linux, `XDG_CONFIG_HOME` is also respected
(previously macOS ignored it).

### `cli/app.py` — V4 CLI flags

- `--voice` enters the voice client.
- `--text` / `--mic` select the voice mode.
- `--host` / `--port` override the daemon endpoint.
- `--no-tts` disables TTS for the reply.

## V5 deltas

### `voice/` — provider-based refactor

The monolithic `voice/tts.py` and `voice/stt.py` were split into provider
subpackages. The agent core only depends on the `TTSBackend` and
`STTBackend` Protocols.

```
voice/
  audio/         — platform-agnostic mic/speaker abstraction
  tts/            — TTS providers
    noop.py
    say_backend.py
    kokoro.py
    openai_tts.py
  stt/            — STT providers
    text_backend.py
    whisper_cpp_stt.py
    whisper_api.py
  render.py       — speech renderer (strips markdown/code/JSON)
  setup.py        — `hyusk voice setup` / `hyusk voice doctor` / `voice test`
  client.py       — the main entry point
```

### `voice/tts/kokoro.py` — Kokoro TTS

Local neural TTS via the `kokoro-onnx` package. The model and voices are
downloaded from `thewh1teagle/kokoro-onnx` GitHub releases on first
use and cached at `~/.cache/hyusk/kokoro/`. Default voice: `af_sarah`
(American English female).

### `voice/stt/whisper_cpp_stt.py` — whisper.cpp STT

Local STT via `pywhispercpp` (Python wrapper around whisper.cpp). The
default model is `base.en` (74 MB). The model is loaded once and
reused. Configurable via `HYUSK_WHISPER_MODEL` env var or
`voice.whisper_model` config value.

### `voice/render.py` — speech renderer

Removes markdown, code blocks, JSON blobs, URLs, tool-call lines, and
list markers from agent output before passing it to TTS. Keeps the
experience conversational.

### `voice/setup.py` — `hyusk voice setup` / `voice doctor` / `voice test`

- `setup`: print a one-time install guide.
- `doctor`: check the voice stack (mic, speaker, TTS, STT, models).
- `test`: synthesize a test phrase using the current TTS.

### `cli/app.py` — `voice` subcommand

::

  hyusk voice setup
  hyusk voice doctor
  hyusk voice test
  hyusk --voice --text          # run the voice client
  hyusk --voice --mic --tts-backend kokoro --stt-backend whisper_cpp

The `voice.tts_backend` and `voice.stt_backend` config keys select the
provider. `voice.tts_voice` selects the voice (e.g. `af_sarah`).

### `pyproject.toml` — V5 dependencies

- `voice` extra: `sounddevice`, `numpy`, `scipy`
- `tts` extra: `kokoro-onnx`, `soundfile`
- `stt` extra: `pywhispercpp`
- `tts-cloud` extra: `httpx`
- `all`: everything

## V1 + V2 + V3 modules (unchanged)

### `core/errors.py` — typed errors

`HyuskError` is the base. Subclasses cover tool, permission, command,
timeout, platform, file, input, provider, loop limit, cancellation,
and steering errors.

### `events/events.py` — typed event bus

`EventBus` is a synchronous pub/sub. `EventType` covers what the
agent and daemon need.

### `llm/` — providers

`LLMProvider.chat()` is the canonical contract. `chat_stream()`
yields `LLMChunk` for streaming support.

### `tools/` — tool base + registry

A `Tool` is a data record: name, description, JSON-schema input,
permission category, `execute()` callable. The agent discovers tools
through `ToolRegistry`; never hardcoded. Plugins register tools
dynamically via the same registry.

### `permissions/policy.py`

`PermissionPolicy` produces `allow` / `deny` / `ask` per call. The
daemon routes `ask` to the originating client.

### `sessions/session.py` + `sessions/store.py`

`Session` is a dataclass. `SessionStore` is a thin wrapper that knows
the base directory. `Task` calls `session.save_self()` to persist
its messages after a run completes.

### `platform/`

OS abstractions: `Shell`, `ProcessManager` (Posix + Windows stubs),
`filesystem` helpers.

## V5+ paths (still no rewrite needed)

| V5+ feature              | Hook                                        |
|--------------------------|---------------------------------------------|
| Mobile client            | Already supported by V3 protocol            |
| Streaming mid-cancel     | Provider-specific mid-stream abort          |
| Persistent PTY shell     | swap `platform.shell.make_shell` factory    |
| Real Windows processes   | add `platform/windows/...`                  |
| Plugin marketplace       | curated registry of community plugins       |
| Sandboxing               | wrap `Tool.run` in a sandboxed executor     |
| Remote daemon            | add auth layer; protocol unchanged          |
| Multi-tenant daemon      | namespace sessions per client token         |

All of these only add code. Nothing in V1/V2/V3/V4 needs to change.
