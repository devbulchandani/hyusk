"""Anthropic Messages API provider (streaming + non-streaming).

V2 implementation. Uses `urllib` so no SDK dependency is required. Supports
both the non-streaming POST and the streaming SSE endpoint.

The Anthropic Messages API differs from OpenAI:
  - System messages are passed as a top-level `system` field, not a message.
  - Tools use `input_schema` directly (no `function` wrapper).
  - Tool calls are `tool_use` content blocks; tool results are `tool_result`
    blocks in a user message (mapped here to/from our internal Message type).

Set the API key with `HYUSK_LLM_PROVIDER=anthropic` + `HYUSK_LLM_MODEL=claude-3-5-sonnet-latest`
+ `HYUSK_LLM_API_KEY=...`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from ..core.errors import ProviderError
from .provider import (
    LLMChunk,
    LLMProvider,
    LLMResponse,
    Message,
    ToolCallRequest,
    ToolSpec,
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "claude-3-5-sonnet-latest",
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        self.default_model = default_model

    # ----- non-streaming -----

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("missing Anthropic API key: set ANTHROPIC_API_KEY or HYUSK_LLM_API_KEY")
        system, api_messages = _convert_messages(messages)
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = float(temperature)
        if tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
        raw = self._post_json("/v1/messages", body)
        return _parse_response(raw)

    # ----- streaming -----

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[LLMChunk]:
        if not self.api_key:
            raise ProviderError("missing Anthropic API key: set ANTHROPIC_API_KEY or HYUSK_LLM_API_KEY")
        system, api_messages = _convert_messages(messages)
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": True,
        }
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = float(temperature)
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        accumulated_text = ""
        # Anthropic tool blocks are emitted incrementally as `input_json_delta`.
        tool_state: dict[int, dict[str, Any]] = {}
        stop_reason: str | None = None

        for ev in self._post_event_stream("/v1/messages", body):
            etype = ev.get("type")
            if etype == "content_block_start":
                cb = ev.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    idx = ev.get("index", 0)
                    tool_state[idx] = {
                        "id": cb.get("id", ""),
                        "name": cb.get("name", ""),
                        "arguments": "",
                    }
            elif etype == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    piece = delta.get("text", "")
                    accumulated_text += piece
                    yield LLMChunk(text_delta=piece)
                elif delta.get("type") == "input_json_delta":
                    idx = ev.get("index", 0)
                    state = tool_state.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    state["arguments"] += delta.get("partial_json", "")
            elif etype == "message_delta":
                if "delta" in ev and "stop_reason" in ev["delta"]:
                    stop_reason = ev["delta"]["stop_reason"]
            # message_start, content_block_stop, message_stop, ping: ignored

        # Build final response
        tool_calls: list[ToolCallRequest] = []
        for idx in sorted(tool_state):
            st = tool_state[idx]
            try:
                args = json.loads(st["arguments"]) if st["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": st["arguments"]}
            tool_calls.append(
                ToolCallRequest(name=st.get("name") or "", arguments=args, id=st.get("id") or None)
            )
        response = LLMResponse(text=accumulated_text, tool_calls=tool_calls, raw={"stop_reason": stop_reason})
        yield LLMChunk(done=True, response=response)

    # ----- HTTP helpers -----

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"Anthropic HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Anthropic network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Anthropic returned invalid JSON: {exc}") from exc

    def _post_event_stream(self, path: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield Anthropic SSE events (each event: type, ...)."""
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"Anthropic HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Anthropic network error: {exc.reason}") from exc
        try:
            event_type = ""
            data_buf: list[str] = []
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if not line:
                    # dispatch
                    if event_type and data_buf:
                        data_str = "\n".join(data_buf)
                        try:
                            payload = json.loads(data_str)
                        except json.JSONDecodeError:
                            payload = {}
                        yield {"type": event_type, **payload}
                    event_type = ""
                    data_buf = []
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[5:].strip())
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


# ---- conversion between Hyusk Message and Anthropic Messages format ----


def _convert_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Convert Hyusk messages -> (system_text, anthropic_messages).

    Hyusk uses OpenAI-style tool messages (role=tool, tool_call_id).
    Anthropic expects role=user with content blocks of type tool_result.
    """
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []

    # Buffer consecutive tool messages into a single user message.
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tools() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            api_messages.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results = []

    for m in messages:
        if m.role == "system":
            if m.content:
                system_parts.append(m.content)
            continue
        if m.role == "tool":
            # Tool result -> Anthropic user-side tool_result block.
            content = m.content or "{}"
            # Try to surface as an object; if not, wrap as string.
            try:
                obj = json.loads(content)
                block_content = obj if isinstance(obj, (dict, list)) else str(obj)
            except json.JSONDecodeError:
                block_content = content
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": block_content,
                }
            )
            continue
        if m.role == "assistant":
            flush_tools()
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id or f"toolu_{len(blocks)}",
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            api_messages.append({"role": "assistant", "content": blocks})
            continue
        if m.role == "user":
            flush_tools()
            api_messages.append({"role": "user", "content": m.content or ""})
            continue
        # Unknown role -> treat as user text.
        flush_tools()
        api_messages.append({"role": "user", "content": str(getattr(m, "content", ""))})

    flush_tools()
    return "\n\n".join(system_parts), api_messages


def _parse_response(raw: dict[str, Any]) -> LLMResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    for block in raw.get("content") or []:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                ToolCallRequest(
                    name=block.get("name") or "",
                    arguments=block.get("input") or {},
                    id=block.get("id"),
                )
            )
    return LLMResponse(text="".join(text_parts), tool_calls=tool_calls, raw=raw)
