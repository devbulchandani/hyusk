"""OpenAI-compatible HTTP provider.

This implementation targets the OpenAI Chat Completions API, which is also
emulated by OpenRouter, Together, Groq, LM Studio, llama.cpp, and most
local OpenAI-compatible servers. No SDK dependency.

For an Anthropic provider later, swap this file with one that calls the
Anthropic Messages API; the agent loop stays unchanged.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..core.errors import ProviderError
from .provider import LLMProvider, LLMResponse, Message, ToolCallRequest, ToolSpec


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str = "", base_url: str = "", default_model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.default_model = default_model

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
        }
        if temperature is not None:
            body["temperature"] = float(temperature)
        if tools:
            body["tools"] = [_tool_to_dict(t) for t in tools]
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"LLM network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc
        return _parse_response(raw)


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
