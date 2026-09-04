"""OpenAI-compatible HTTP provider (streaming + non-streaming).

Works with OpenAI, OpenRouter, Together, Groq, LM Studio, llama.cpp, etc.

V2 adds SSE streaming via `chat_stream()`.
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


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str = "", base_url: str = "", default_model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
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
            raise ProviderError("missing API key: set OPENAI_API_KEY or HYUSK_LLM_API_KEY")
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [_message_to_dict(m) for m in messages],
            "stream": False,
        }
        if temperature is not None:
            body["temperature"] = float(temperature)
        if tools:
            body["tools"] = [_tool_to_dict(t) for t in tools]
            body["tool_choice"] = "auto"
        raw = self._post_json("/chat/completions", body)
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
            raise ProviderError("missing API key: set OPENAI_API_KEY or HYUSK_LLM_API_KEY")
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [_message_to_dict(m) for m in messages],
            "stream": True,
        }
        if temperature is not None:
            body["temperature"] = float(temperature)
        if tools:
            body["tools"] = [_tool_to_dict(t) for t in tools]
            body["tool_choice"] = "auto"

        accumulated_text = ""
        # Map of tool_call_index -> {id, name, arguments(str)}
        tool_state: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        for sse in self._post_stream("/chat/completions", body):
            chunk = sse.get("choices", [{}])[0]
            delta = chunk.get("delta") or {}
            if "content" in delta and delta["content"]:
                accumulated_text += delta["content"]
                yield LLMChunk(text_delta=delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                state = tool_state.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    state["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    state["name"] += fn["name"]
                if "arguments" in fn:
                    state["arguments"] += fn["arguments"]
                # Yield partial so consumers can show progress; the agent
                # loop ignores partials and only acts on the final response.
                ends_balanced = state["arguments"].rstrip().endswith(("}", "]"))
                if ends_balanced:
                    try:
                        args_obj = json.loads(state["arguments"])
                    except json.JSONDecodeError:
                        args_obj = None
                else:
                    args_obj = None
                if args_obj is not None:
                    yield LLMChunk(
                        tool_call_delta=ToolCallRequest(
                            name=state["name"] or "",
                            arguments=args_obj,
                            id=state["id"] or None,
                        )
                    )
            if chunk.get("finish_reason"):
                finish_reason = chunk["finish_reason"]

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
        response = LLMResponse(
            text=accumulated_text,
            tool_calls=tool_calls,
            raw={"finish_reason": finish_reason},
        )
        yield LLMChunk(done=True, response=response)

    # ----- HTTP helpers -----

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"LLM network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

    def _post_stream(self, path: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield SSE chunks from a streaming endpoint."""
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"LLM network error: {exc.reason}") from exc

        try:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


def _message_to_dict(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role}
    if m.role == "tool":
        out["content"] = m.content or ""
        out["tool_call_id"] = m.tool_call_id or ""
        if m.name:
            out["name"] = m.name
        return out
    out["content"] = m.content or ""
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id or f"call_{i}",
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for i, tc in enumerate(m.tool_calls)
        ]
    return out


def _tool_to_dict(t: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }


def _parse_response(raw: dict[str, Any]) -> LLMResponse:
    choices = raw.get("choices") or []
    if not choices:
        raise ProviderError("LLM returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    tool_calls: list[ToolCallRequest] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw)
            if not isinstance(args, dict):
                args = {"_raw": str(args)}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        tool_calls.append(ToolCallRequest(name=fn.get("name") or "", arguments=args, id=tc.get("id")))
    return LLMResponse(text=text, tool_calls=tool_calls, raw=raw)
