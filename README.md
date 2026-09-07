# HYUSK

**A local-first, persistent, voice-controlled AI operating layer for your personal computer.**

Hyusk is not a chatbot. It's a foundation for a Jarvis-like personal AI system that can:

- 🎤 Understand voice commands and respond naturally
- 💻 Control your computer, applications, and files
- 🔧 Execute terminal commands safely
- 🌐 Browse the web and interact with services
- 🤖 Spawn and supervise coding/research agents
- 📝 Remember context and learn from interactions
- 📱 Be controlled remotely from your phone
- 🔒 Ask for permission before sensitive operations
- 🏠 Work locally whenever possible

## Philosophy

Hyusk is built with a clear architecture:

```
USER → INTERFACE → HYUSK CORE → LLM/PLANNER → PERMISSION ENGINE → TOOL SYSTEM → COMPUTER
```

The LLM decides what it wants to accomplish. The Hyusk runtime decides whether an operation is allowed. The tool implementation performs the actual operation. **The LLM never bypasses the permission system.**

## Status

🚧 **Early Development** - Hyusk is currently under active development. The core architecture is being implemented.

### Implemented

- ✅ Project foundation and structure
- ✅ Core domain models
- ✅ Configuration system
- ✅ Database with migrations
- ✅ Event bus
- ✅ Structured logging

### In Progress

- 🔄 LLM abstraction layer
- 🔄 Tool system and registry
- 🔄 Permission engine

### Planned

- ⏳ Voice system (wake word, STT, TTS)
- ⏳ Computer control (macOS)
- ⏳ Task management
- ⏳ Agent runtime
- ⏳ Memory system
- ⏳ Remote API and phone interface

## Installation

### Prerequisites

- Python 3.12 or higher
- macOS (initial target platform)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended for dependency management)

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/hyusk.git
cd hyusk

# Install dependencies
uv sync

# Configure Hyusk
cp .env.example .env
# Edit .env with your configuration

# Check system requirements
uv run hyusk doctor

# Initialize the database
uv run hyusk init

# Start using Hyusk
uv run hyusk
```

## Quick Start

### Text Chat

```bash
hyusk chat
```

### Voice Mode (coming soon)

```bash
hyusk voice
```

### Start as Daemon (coming soon)

```bash
hyusk daemon start
```

## Configuration

Hyusk uses a configuration file located at `~/.config/hyusk/config.yaml`.

Example configuration:

```yaml
llm:
  default_provider: anthropic
  models:
    default: claude-sonnet-4
    fast: claude-haiku-3.5
    coding: claude-sonnet-4
    vision: claude-sonnet-4

voice:
  enabled: false
  wake_word: "hey hyusk"
  stt:
    provider: whisper
    model: base
  tts:
    provider: kokoro
    voice: default

permissions:
  auto_approve_safe: true
  require_confirmation:
    - write_file
    - terminal_execute
    - delete_file

computer:
  platform: macos

agents:
  max_concurrent: 5
  workspace_dir: ~/.hyusk/workspaces

memory:
  enabled: true
  vector_search: false

remote:
  enabled: false
  host: localhost
  port: 8765
```

## Architecture

Hyusk is designed with clean separation of concerns:

- **Core**: Orchestrator, context management, lifecycle
- **LLM**: Provider abstraction, routing, message handling
- **Tools**: Registry, execution, validation
- **Permissions**: Policy engine, approval system
- **Voice**: Wake word detection, STT, TTS
- **Computer**: Platform-specific system integration
- **Agents**: Task execution, workspace management
- **Memory**: Context storage, retrieval
- **Remote**: API server, WebSocket events

See [docs/architecture.md](docs/architecture.md) for detailed information.

## Development

### Setup Development Environment

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
pytest

# Run linter
ruff check .

# Run type checker
mypy src/hyusk

# Format code
ruff format .
```

### Project Structure

```
hyusk/
├── src/hyusk/          # Main package
│   ├── core/           # Core orchestration
│   ├── llm/            # LLM providers
│   ├── tools/          # Tool implementations
│   ├── permissions/    # Permission system
│   ├── voice/          # Voice I/O
│   ├── computer/       # System integration
│   ├── agents/         # Agent runtime
│   ├── tasks/          # Task management
│   ├── memory/         # Memory system
│   └── cli/            # CLI interface
├── tests/              # Test suite
├── docs/               # Documentation
└── scripts/            # Utility scripts
```

## Security

Hyusk takes security seriously:

- **Permission System**: All sensitive operations require explicit approval
- **Command Validation**: Terminal commands are validated before execution
- **Path Protection**: Filesystem operations are restricted to safe locations
- **Secret Management**: API keys and credentials are never exposed to the LLM
- **Audit Logging**: All operations are logged for transparency

See [docs/security.md](docs/security.md) for more information.

## Roadmap

### Phase 1: Foundation ✅
- Project structure
- Core models
- Configuration
- Database
- Event bus

### Phase 2: LLM Integration 🔄
- Provider abstraction
- Tool calling
- Message handling

### Phase 3: Tool System 🔄
- Tool registry
- Filesystem tools
- Terminal execution

### Phase 4: Permissions 🔄
- Permission engine
- Approval system
- Policy management

### Phase 5: Computer Control
- macOS integration
- Application control
- Screenshot capture
- Keyboard/mouse control

### Phase 6: Voice
- Wake word detection
- Whisper.cpp STT
- Kokoro TTS
- Voice conversation loop

### Phase 7: Tasks & Agents
- Task management
- Agent runtime
- Coding agent
- Workspace isolation

### Phase 8: Memory
- Conversation memory
- Context retrieval
- Long-term storage

### Phase 9: Remote Access
- REST API
- WebSocket events
- Phone PWA

### Phase 10: Production Ready
- Security hardening
- Performance optimization
- Documentation
- Installer

## Contributing

Contributions are welcome! Please read our contributing guidelines first.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Hyusk stands on the shoulders of giants:

- LLM providers: Anthropic, OpenAI
- Voice: Whisper.cpp, Kokoro
- And many other open-source projects

---

**Note**: Hyusk is under active development. The API and architecture may change as we iterate towards a stable release.
