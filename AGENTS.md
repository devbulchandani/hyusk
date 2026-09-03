# Build V1 of `hyusk` — Cross-Platform Computer Agent

You are building **hyusk**, a cross-platform computer-control agent whose long-term goal is to let a user control their Mac/Windows/Linux computer through natural language, voice, and eventually a mobile app.

For V1, **do not try to build the entire vision**. Build a solid, production-quality foundation that future voice clients, phone clients, remote connections, and coding-agent integrations can use.

## 1. First: inspect the environment

Before writing code:

* Inspect the current directory.
* Determine what tools/languages/runtimes are already installed.
* Check whether this directory is already a Git repository.
* Check that `gh` is installed and authenticated.
* Check available versions of the chosen runtime/toolchain.
* Do not blindly install a large dependency stack if an appropriate lightweight option is already available.

If the current directory is empty or suitable for the project, initialize the project there.

Use `gh` CLI to create the GitHub repository and push the project once the initial implementation is ready.

The repository should be named:

`hyusk`

If the GitHub owner/account is ambiguous, inspect `gh auth status` and use the authenticated account.

Do NOT create unnecessary organizations, repositories, branches, or infrastructure.

---

# 2. Product vision

Hyusk is intended to become a **computer agent**, not merely a chatbot.

The eventual architecture should support:

```text
                 ┌─────────────────────┐
                 │      HYUSK CORE      │
                 │                     │
                 │ Agent / Planner     │
                 │ Tool Registry       │
                 │ Permissions         │
                 │ Session Manager     │
                 │ Event System        │
                 └──────────┬──────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
       Terminal          Computer          Processes
       Manager           Control            Manager
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                  OS-specific adapters
                            │
                ┌───────────┼───────────┐
                │           │           │
              macOS       Linux      Windows

Clients eventually include:

CLI
Voice
Mobile app
Web UI
Remote clients
Other agents
```

V1 should establish the architecture for this without implementing every future feature.

---

# 3. Core V1 functionality

Build a working local CLI agent.

Running:

```bash
hyusk
```

should start an interactive session.

For example:

```text
$ hyusk

hyusk > list the files in this directory

I'll inspect the current directory.

→ list_directory(".")

...

hyusk >
```

Also support one-shot commands:

```bash
hyusk "show me the processes currently using the most CPU"
```

and preferably:

```bash
hyusk run "git status"
```

if this fits naturally into the architecture.

The exact CLI syntax is your design decision, but it must feel clean and Unix-friendly.

---

# 4. Agent architecture

Keep the codebase **strictly modular and clean**.

Do NOT create one giant `main.py`, `index.ts`, `app.go`, etc.

Separate:

### CLI layer

Responsible only for:

* argument parsing
* interactive REPL
* rendering output
* user interaction

It should NOT contain agent logic.

### Agent layer

Responsible for:

* conversation/session state
* model interaction
* deciding when to use tools
* executing tool calls
* handling tool results
* iteration/agent loop
* stopping conditions

### Tool layer

Create a proper tool abstraction.

Conceptually:

```text
Tool
 ├── name
 ├── description
 ├── input schema
 ├── permission level
 └── execute()
```

Example tools:

```text
shell.execute
filesystem.list
filesystem.read
filesystem.write
process.list
process.kill
git.status
```

Do not hardcode these directly into the agent loop.

Create a registry:

```text
ToolRegistry
    register(tool)
    get(name)
    list()
```

The agent should discover available tools through the registry.

---

# 5. Shell execution

Implement a robust shell tool.

It should support:

```text
command
working directory
environment
timeout
stdout
stderr
exit code
```

Do not simply use an unsafe string concatenation approach.

The abstraction should eventually support persistent terminals, so design it with future PTY/session support in mind.

For V1, a basic command execution implementation is sufficient.

Example conceptual result:

```json
{
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_ms": 124
}
```

The agent must be able to understand command failures.

---

# 6. Filesystem tools

Implement at least:

```text
list_directory
read_file
write_file
```

Include sensible safety limits.

For example:

* prevent accidentally dumping enormous files into model context
* truncate very large command output
* return useful metadata
* handle nonexistent files gracefully
* handle permission errors gracefully

Do not implement arbitrary filesystem access in a way that makes it impossible to add a permission/sandbox layer later.

---

# 7. Process management

Implement:

```text
list_processes
kill_process
```

The process abstraction must be OS-aware.

Do NOT assume Linux-only commands such as `ps` are the universal implementation.

Create an OS abstraction such as:

```text
ProcessManager
```

with platform-specific implementations where appropriate:

```text
MacProcessManager
LinuxProcessManager
WindowsProcessManager
```

V1 can have limited platform support, but the architecture must make adding the other platforms straightforward.

If some functionality is unavailable on the current OS, return a structured unsupported-operation error rather than crashing.

---

# 8. Git integration

Create a Git tool layer.

At minimum:

```text
git.status
git.diff
git.log
```

Optionally:

```text
git.branch
```

The agent should understand the current repository context.

Do not tightly couple Git functionality to the CLI.

---

# 9. Permissions / safety

This is extremely important.

Hyusk will eventually have the ability to control an entire computer, so permissions must be an architectural concept from V1.

Every tool should have a permission category.

For example:

```text
READ
WRITE
EXECUTE
DESTRUCTIVE
```

Potentially:

```text
READ:
  list files
  read files
  inspect processes
  git status

WRITE:
  modify files
  create files

EXECUTE:
  run shell commands

DESTRUCTIVE:
  delete files
  kill processes
```

Build a permission interface even if V1's policy is relatively simple.

The agent should never have an architecture where every tool automatically gets unlimited authority.

Make it possible to later implement:

```text
"Allow hyusk to run this command? [y/N]"
```

and:

```text
Always allow this tool
Allow once
Deny
```

---

# 10. Configuration

Create a clean configuration system.

For example:

```text
~/.config/hyusk/
```

or the appropriate platform-specific configuration directory.

Configuration should eventually support:

```text
model provider
API key
default model
tool permissions
logging
agent behavior
```

Do not hardcode API keys.

Support environment variables and/or a config file.

Document the configuration clearly.

---

# 11. LLM abstraction

Do NOT hardwire the entire application to one specific model provider.

Create an interface such as:

```text
LLMProvider
```

with responsibilities like:

```text
chat()
stream()
```

The agent should depend on the abstraction, not directly on provider-specific SDK code.

Implement one provider for V1.

Choose a sensible provider based on what is already available in the environment, but keep the provider implementation isolated.

The architecture should make it straightforward to later add:

```text
OpenAI
Anthropic
OpenRouter
local models
etc.
```

without rewriting the agent.

---

# 12. Streaming

Prefer streaming model output in the CLI.

For example:

```text
hyusk > explain why my tests are failing

I'll inspect the project...

→ shell.execute(...)
```

The user should see useful progress rather than waiting for one huge response.

Tool calls should also be rendered clearly.

Example:

```text
┌─ shell.execute
│ npm test
└────────────────────────

...

exit code: 1
```

Keep the UI clean. Avoid excessive decoration.

---

# 13. Agent loop

Implement a proper agent loop.

Conceptually:

```text
User input
    ↓
Agent
    ↓
LLM
    ↓
Text OR tool call
    ↓
Tool execution
    ↓
Tool result
    ↓
LLM
    ↓
...
    ↓
Final response
```

The agent should support multiple tool calls when necessary.

Include safeguards against infinite loops:

```text
max iterations
timeouts
tool execution limits
```

Make these configurable.

---

# 14. Persistent sessions

Create a session abstraction now even if persistence is basic.

Conceptually:

```text
Session
 ├── id
 ├── messages
 ├── created_at
 └── metadata
```

The CLI should have a way to start a new session and continue an existing one if practical for V1.

This is important because the future phone application will need to reconnect to existing agent sessions.

---

# 15. Event architecture

Introduce a lightweight internal event system or event abstraction.

Future clients will need events such as:

```text
agent.started
agent.thinking
tool.started
tool.output
tool.completed
process.started
process.exited
agent.completed
agent.error
```

Do not overengineer this.

A simple typed event model is enough for V1.

But keep events independent from terminal rendering.

The CLI should subscribe to events rather than the core agent directly printing to stdout.

This will make future WebSocket/mobile clients much easier.

---

# 16. Daemon architecture

Even though V1 can primarily be a local CLI, structure the application so a daemon can be introduced cleanly.

Ideally:

```text
hyusk
```

is a client.

Eventually:

```text
hyusk daemon
```

runs the persistent local service.

Do NOT implement a complicated network server unless it is genuinely useful for V1.

Instead, establish interfaces so this transition does not require rewriting the core.

Future architecture:

```text
CLI ─────────────┐
                 │
Voice ───────────┤
                 ▼
             Hyusk API
                 │
                 ▼
           Hyusk Daemon
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
     Tools    Sessions   Events
```

---

# 17. Platform architecture

The core should be platform-independent.

Use interfaces/ports for OS functionality.

For example:

```text
OperatingSystem
Shell
ProcessManager
Filesystem
ApplicationManager
```

Then provide implementations such as:

```text
platform/
    macos/
    linux/
    windows/
```

Do not create three copies of the entire application.

Only OS-specific capabilities should differ.

For V1, prioritize the current development OS, but make the boundaries explicit.

---

# 18. Error handling

Errors should be structured.

Avoid:

```text
try:
    ...
except:
    print("something went wrong")
```

Prefer typed/domain errors where appropriate.

The agent should be able to distinguish:

```text
ToolNotFound
PermissionDenied
CommandFailed
Timeout
UnsupportedPlatform
FileNotFound
InvalidInput
ProviderError
```

The CLI can then turn those into friendly messages.

---

# 19. Logging

Implement structured logging.

Support at least:

```text
debug
info
warning
error
```

Do not dump secrets into logs.

API keys, tokens, environment secrets, etc. must never be logged.

---

# 20. Testing

Write tests for the important architectural pieces.

At minimum test:

### Tool registry

* registration
* lookup
* duplicate handling
* missing tools

### Shell tool

* successful command
* failed command
* timeout
* stdout/stderr

### Filesystem

* read
* write
* missing files
* size limits

### Agent loop

Mock the LLM provider and verify:

```text
LLM → tool call → tool result → LLM → final answer
```

### Permissions

Verify denied tools are never executed.

### Process abstraction

Test using mocks/fakes where platform-specific behavior makes unit testing difficult.

Do not make the entire test suite dependent on external APIs.

---

# 21. Documentation

Create a high-quality `README.md`.

It should explain:

```text
What is Hyusk?
Why does it exist?
Architecture
Installation
Configuration
Usage
Available tools
Security model
Development
Testing
Roadmap
```

Include examples:

```bash
hyusk
```

```bash
hyusk "what files are in this project?"
```

```bash
hyusk "show me the processes using the most CPU"
```

Also explain that Hyusk is currently V1 and that voice/mobile/remote control are planned.

Create an architecture document:

```text
docs/architecture.md
```

Document the major interfaces and boundaries.

---

# 22. Code quality rules

Follow these strictly:

* Keep functions small.
* Prefer composition over giant classes.
* Avoid global mutable state.
* Avoid circular dependencies.
* Keep infrastructure separate from domain logic.
* Keep CLI rendering separate from agent logic.
* Keep LLM provider code separate from the agent.
* Keep OS-specific code behind interfaces.
* Keep tools independently testable.
* Use strong typing where the language supports it.
* Validate external input.
* Never silently swallow exceptions/errors.
* Avoid premature abstractions, but establish boundaries that are clearly required by the product vision.
* Do not introduce a framework just because it is popular.
* Minimize dependencies.
* Prefer boring, maintainable code over clever code.

The code should be something another strong engineer could comfortably take over.

---

# 23. Suggested project structure

Adapt this to the language you choose, but aim for a structure roughly like:

```text
hyusk/
├── README.md
├── LICENSE
├── .gitignore
├── docs/
│   └── architecture.md
├── src/
│   └── hyusk/
│       ├── cli/
│       ├── agent/
│       ├── llm/
│       ├── tools/
│       │   ├── filesystem/
│       │   ├── shell/
│       │   ├── process/
│       │   └── git/
│       ├── permissions/
│       ├── sessions/
│       ├── events/
│       ├── platform/
│       │   ├── macos/
│       │   ├── linux/
│       │   └── windows/
│       ├── config/
│       └── core/
├── tests/
│   ├── agent/
│   ├── tools/
│   ├── permissions/
│   └── ...
└── ...
```

The exact structure can differ if the chosen language has a more idiomatic convention.

---

# 24. Technology selection

Before implementation, briefly evaluate the available options and choose a language/runtime that is appropriate for:

* cross-platform CLI
* long-running daemon
* subprocess/PTY management
* filesystem/process management
* networking
* future mobile API
* good developer experience
* strong typing/reliability

Do not choose a technology merely because it is trendy.

If there is an existing project in the directory, respect its technology unless there is a compelling reason to change it.

---

# 25. Git workflow

Initialize Git if necessary.

Create the project with meaningful commits.

Do NOT make one enormous commit.

Use commits approximately like:

```text
chore: initialize hyusk project
feat: add configuration system
feat: add tool registry
feat: add shell tool
feat: add filesystem tools
feat: add process tools
feat: add git tools
feat: add agent loop
feat: add session management
feat: add CLI interface
test: add core agent coverage
docs: add architecture documentation
```

You don't have to use exactly these commits if a different breakdown makes more sense.

Before every commit:

* run formatting
* run linting
* run tests
* inspect the diff

Do not commit generated junk, secrets, `.env` files, API keys, build artifacts, caches, or local credentials.

---

# 26. GitHub repository

Once the project is working:

1. Verify Git status.
2. Verify no secrets are present.
3. Run the complete test suite.
4. Review the final diff.
5. Initialize/create the GitHub repository using `gh`.
6. Make it public unless there is a clear reason not to.
7. Add the remote.
8. Push the default branch.
9. Verify the remote repository exists.
10. Ensure the README renders correctly.

Use the authenticated `gh` account.

Do not expose credentials in commits or command output.

---

# 27. Definition of Done

V1 is complete only when:

* `hyusk` launches successfully.
* Interactive CLI works.
* One-shot commands work.
* The LLM can invoke tools.
* Shell execution works.
* Filesystem tools work.
* Process inspection works.
* Git inspection works.
* Tool permissions exist.
* Agent loops safely terminate.
* Sessions have a clean abstraction.
* Events are separated from presentation.
* Configuration works.
* Errors are handled cleanly.
* Tests pass.
* Formatting/linting pass.
* README is useful.
* Architecture documentation exists.
* No secrets are committed.
* Git history is clean and meaningful.
* GitHub repository is created through `gh`.
* Initial implementation is pushed successfully.

---

# 28. Important: don't overbuild

This is V1.

Do NOT implement yet:

* wake-word detection
* voice transcription
* text-to-speech
* mobile application
* cloud backend
* remote internet access
* distributed agent infrastructure
* elaborate GUI
* autonomous background behavior
* arbitrary browser automation
* screen/computer vision control
* complicated plugin marketplace

However, **design the interfaces so those things can be added later without rewriting the core.**

The most important goal is:

> Build a small, clean, extensible computer-agent core that can become the foundation of Hyusk.

---

# Execution instructions

Work autonomously.

Do not stop after creating a skeleton.

Actually implement the working V1.

When you encounter a design decision, prefer the simplest solution that preserves the architecture described above.

After implementation:

1. Run tests.
2. Fix failures.
3. Run lint/format/type checks.
4. Test the CLI manually.
5. Inspect Git diff.
6. Commit the changes in logical commits.
7. Create the GitHub repository with `gh`.
8. Push the commits.
9. Verify the remote.
10. Give me a concise final report containing:

* chosen tech stack and why
* implemented functionality
* project structure
* test results
* GitHub repository URL
* important V2 recommendations

Do not claim something works unless you actually tested it.

