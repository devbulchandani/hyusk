"""Agent loop.

Turns a user message into a series of LLM calls, tool executions, and a
final answer. Emits events so the CLI (and V2/V3 transports) can render
progress in real time.

V2 features:
  - When the LLM provider supports `chat_stream`, the agent loop uses it
    and emits AGENT_TEXT with `delta=True` for each chunk. Non-streaming
    providers fall back to a single AGENT_TEXT with `delta=False`.

V3 features:
  - Concurrent runs are not blocked by each other. Each Agent has its
    own thread, its own EventBus, and its own session_messages buffer.
  - Steering: a host can call `agent.inject_steering("...")` to queue
    a follow-up user message. The agent loop drains the queue between
    tool calls (i.e. before the next LLM call) and appends the message
    to the conversation. The current tool call is **not** interrupted.
  - Cancellation: `agent.cancel()` sets a flag. The agent loop checks
    the flag between tool calls and between LLM calls. The current
    streaming LLM call is **not** aborted (that would require provider-
    specific cancellation); instead, the loop exits as soon as the call
    returns and the run completes with state="cancelled".

Safeguards:
  - max_iterations prevents runaway loops
  - tool errors are returned to the model instead of crashing
  - permission policy is enforced before every tool execution
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from ..core.errors import AgentCancelled, AgentLoopLimit
from ..events.events import Event, EventBus, EventType
from ..llm.provider import LLMProvider, LLMResponse, Message, ToolCallRequest, ToolSpec
from ..permissions.policy import PermissionPolicy
from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry

SYSTEM_PROMPT = """You are Hyusk, a cross-platform computer agent. You help the user
control their computer through natural language.

You can call tools to inspect files, run shell commands, manage processes,
and inspect git repositories. Prefer minimal, focused tool calls. Always
explain what you are about to do before calling a tool.

When you have enough information, give a concise final answer. Do not call
tools when a direct answer is possible.

You may receive follow-up instructions from the user while a previous
task is in progress. Treat them as new directives: acknowledge them
briefly, then continue with the most useful action.
"""


@dataclass
class AgentResult:
    text: str
    iterations: int
    session_messages: list[Message]
    cancelled: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


GrantCallback = Callable[[str, dict], bool]


class Agent:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        bus: EventBus,
        model: str = "",
        max_iterations: int = 25,
        grant_callback: GrantCallback | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.policy = policy
        self.bus = bus
        self.model = model
        self.max_iterations = max_iterations
        self.grant_callback = grant_callback
        # V3: thread-safe steering queue and cancel flag.
        self._steering: list[str] = []
        self._steering_lock = threading.Lock()
        self._cancelled = threading.Event()
        # Streaming detection (unchanged from V2).
        try:
            cls = type(llm)
            self._supports_streaming = cls.chat_stream is not LLMProvider.chat_stream
        except AttributeError:
            self._supports_streaming = False

    # ---- public API ----

    def inject_steering(self, message: str) -> None:
        """Queue a follow-up user message. The agent will see it after the
        current tool call (or before the next LLM call if no tool is running)."""
        if not message:
            return
        with self._steering_lock:
            self._steering.append(message)
        self._emit(EventType.AGENT_TEXT, {"delta": False, "text": "\n[steer queued]\n"})

    def cancel(self) -> None:
        """Request cancellation. The loop checks this flag between LLM/tool calls."""
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def run(
        self,
        messages: list[Message],
        *,
        user_input: str | None = None,
    ) -> AgentResult:
        if user_input:
            messages.append(Message(role="user", content=user_input))
        if not messages or messages[0].role != "system":
            messages.insert(0, Message(role="system", content=SYSTEM_PROMPT))

        self._emit(EventType.AGENT_STARTED, {"messages": len(messages)})

        tool_specs: list[ToolSpec] = [
            ToolSpec(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in self.registry.all()
        ]
        self._emit(
            EventType.AGENT_TOOL_CALL,
            {"available_tools": [t.name for t in tool_specs]},
        )

        iterations = 0
        final_text = ""
        result_error: str | None = None
        cancelled = False

        try:
            while iterations < self.max_iterations:
                if self._cancelled.is_set():
                    cancelled = True
                    break

                # Drain steering messages between iterations.
                self._drain_steering(messages)

                iterations += 1
                self._emit(EventType.AGENT_THINKING, {"iteration": iterations})

                if self._supports_streaming:
                    response = self._stream_chat(messages, tool_specs)
                else:
                    response = self.llm.chat(messages, tools=tool_specs, model=self.model or None)
                    if response.text:
                        self._emit(EventType.AGENT_TEXT, {"delta": False, "text": response.text})

                if response.text:
                    final_text = response.text

                if not response.wants_tool:
                    break

                messages.append(
                    Message(
                        role="assistant",
                        content=response.text or "",
                        tool_calls=list(response.tool_calls),
                    )
                )
                for tc in response.tool_calls:
                    if self._cancelled.is_set():
                        cancelled = True
                        break
                    self._handle_tool_call(tc, messages)
                if cancelled:
                    break

            if iterations >= self.max_iterations and final_text == "" and not cancelled:
                raise AgentLoopLimit(f"reached max iterations ({self.max_iterations})")
        except AgentCancelled:
            cancelled = True
        except AgentLoopLimit:
            # V2 contract: AgentLoopLimit propagates so callers can detect
            # hard limits. V3 callers (Task) handle this explicitly.
            raise
        except Exception as exc:  # noqa: BLE001
            result_error = f"{type(exc).__name__}: {exc}"
            self._emit(EventType.AGENT_ERROR, {"error": result_error})

        self._emit(
            EventType.AGENT_COMPLETED,
            {
                "iterations": iterations,
                "text_chars": len(final_text),
                "cancelled": cancelled,
                "error": result_error,
            },
        )
        return AgentResult(
            text=final_text,
            iterations=iterations,
            session_messages=messages,
            cancelled=cancelled,
            error=result_error,
        )

    # ---- internals ----

    def _drain_steering(self, messages: list[Message]) -> None:
        with self._steering_lock:
            pending = list(self._steering)
            self._steering.clear()
        for msg in pending:
            messages.append(Message(role="user", content=msg))
            self._emit(EventType.AGENT_TEXT, {"delta": False, "text": f"\n[steer] {msg}\n"})

    def _stream_chat(self, messages: list[Message], tool_specs: list[ToolSpec]) -> LLMResponse:
        """Run chat_stream and emit one AGENT_TEXT per text chunk."""
        final: LLMResponse | None = None
        try:
            stream = self.llm.chat_stream(messages, tools=tool_specs, model=self.model or None)
        except NotImplementedError:
            return self.llm.chat(messages, tools=tool_specs, model=self.model or None)
        for chunk in stream:
            if self._cancelled.is_set():
                # Stop consuming the stream; whatever we've got is the final.
                break
            if chunk.text_delta:
                self._emit(EventType.AGENT_TEXT, {"delta": True, "text": chunk.text_delta})
            if chunk.done:
                final = chunk.response
        if final is None:
            return self.llm.chat(messages, tools=tool_specs, model=self.model or None)
        return final

    def _handle_tool_call(self, tc: ToolCallRequest, messages: list[Message]) -> None:
        if not self.registry.has(tc.name):
            err = {"error": f"unknown tool: {tc.name}"}
            self._emit(EventType.TOOL_COMPLETED, {"name": tc.name, "error": err["error"]})
            messages.append(
                Message(
                    role="tool",
                    name=tc.name,
                    tool_call_id=tc.id,
                    content=json.dumps(err),
                )
            )
            return

        tool = self.registry.get(tc.name)
        decision = self.policy.decide(tool)

        if decision.action == "deny":
            err = {"error": decision.reason or "denied"}
            self._emit(EventType.TOOL_COMPLETED, {"name": tc.name, "error": err["error"]})
            messages.append(
                Message(
                    role="tool",
                    name=tc.name,
                    tool_call_id=tc.id,
                    content=json.dumps(err),
                )
            )
            return

        if decision.action == "ask":
            granted = bool(self.grant_callback and self.grant_callback(tc.name, tc.arguments))
            if not granted:
                err = {"error": "interactive approval denied"}
                self._emit(EventType.TOOL_COMPLETED, {"name": tc.name, "error": err["error"]})
                messages.append(
                    Message(
                        role="tool",
                        name=tc.name,
                        tool_call_id=tc.id,
                        content=json.dumps(err),
                    )
                )
                return

        self._emit(EventType.TOOL_STARTED, {"name": tc.name, "arguments": tc.arguments})
        start = time.time()
        result = ToolResult(name=tc.name, arguments=tc.arguments, output={}, error=None, duration_ms=0)
        try:
            output = tool.run(tc.arguments)
            if isinstance(output, dict) and "error" in output and len(output) == 1:
                result.error = str(output["error"])
            result.output = output if isinstance(output, dict) else {"value": output}
        except Exception as exc:  # noqa: BLE001
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.time() - start) * 1000)
        self._emit(
            EventType.TOOL_COMPLETED,
            {"name": tc.name, "duration_ms": result.duration_ms, "error": result.error},
        )
        messages.append(
            Message(
                role="tool",
                name=tc.name,
                tool_call_id=tc.id,
                content=json.dumps(result.output, default=str),
            )
        )

    def _emit(self, event_type: EventType, data: dict) -> None:
        self.bus.publish(Event(type=event_type, data=data))


def events_to_messages(
    agent: Agent,
    messages: list[Message],
    *,
    user_input: str | None,
) -> EventStream:
    """Run the agent in a background thread; returns an EventStream."""
    return EventStream(agent, messages, user_input=user_input)


class EventStream:
    """Runs an Agent.run() in a background thread and yields its events.

    Used by transports (V2/V3 daemon WebSocket handler) that need to consume
    the agent's event stream from another thread without coupling to the
    Agent's lifetime directly.
    """

    def __init__(self, agent: Agent, messages: list[Message], *, user_input: str | None) -> None:
        self._queue: list[Event] = []
        self._lock = threading.Lock()
        self._done = False
        self._error: Exception | None = None
        self._result: AgentResult | None = None

        def on_event(ev: Event) -> None:
            with self._lock:
                self._queue.append(ev)

        self._unsub = agent.bus.subscribe(on_event)

        def runner() -> None:
            try:
                res = agent.run(list(messages), user_input=user_input)
                self._result = res
            except Exception as exc:  # noqa: BLE001
                self._error = exc
            finally:
                with self._lock:
                    self._done = True

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def __iter__(self) -> Iterator[Event]:
        return self

    def __next__(self) -> Event:
        while True:
            with self._lock:
                if self._queue:
                    return self._queue.pop(0)
                if self._done:
                    self._unsub()
                    if self._error:
                        raise self._error
                    raise StopIteration
            time.sleep(0.005)

    @property
    def result(self) -> AgentResult | None:
        return self._result
