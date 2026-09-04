"""Streaming tests for the LLM provider interface."""

from __future__ import annotations

from hyusk.llm.openai_compat import OpenAICompatProvider
from hyusk.llm.provider import LLMChunk, LLMProvider, LLMResponse, Message


def test_default_chat_stream_yields_one_done_chunk():
    """A provider that doesn't override chat_stream should still yield
    a single done chunk with the chat() response."""

    class NoStream(LLMProvider):
        name = "no-stream"

        def chat(self, messages, tools=None, *, model=None, temperature=None):
            return LLMResponse(text="hello")

    p = NoStream()
    chunks = list(p.chat_stream([], tools=None))
    # Should yield: a text_delta chunk + a done chunk (or just done).
    done_chunks = [c for c in chunks if c.done]
    assert len(done_chunks) == 1
    assert done_chunks[0].response is not None
    assert done_chunks[0].response.text == "hello"


def test_chunks_dataclass_shape():
    c = LLMChunk(text_delta="hi")
    assert c.text_delta == "hi"
    assert not c.done
    assert c.tool_call_delta is None

    c2 = LLMChunk(done=True, response=LLMResponse(text="x"))
    assert c2.done
    assert c2.response is not None


def test_streaming_provider_stream_method_exists():
    p = OpenAICompatProvider(api_key="x", default_model="x")
    assert hasattr(p, "chat_stream")
    assert callable(p.chat_stream)


def test_message_to_dict_includes_tool_calls():
    """Smoke test that message conversion works for both roles."""
    from hyusk.llm.openai_compat import _message_to_dict

    m_user = Message(role="user", content="hi")
    d = _message_to_dict(m_user)
    assert d["role"] == "user"
    assert d["content"] == "hi"

    m_tool = Message(role="tool", name="x", tool_call_id="c1", content="{}")
    d2 = _message_to_dict(m_tool)
    assert d2["role"] == "tool"
    assert d2["tool_call_id"] == "c1"
    assert d2["name"] == "x"
