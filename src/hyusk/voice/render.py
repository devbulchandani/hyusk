"""Speech renderer: transform agent output into speakable text.

The agent often returns text with markdown, code blocks, JSON, tool
traces, etc. None of that should be spoken verbatim. This module
removes those non-spoken parts and returns plain prose suitable for
TTS.

Two entry points:

* :func:`render_for_speech` — apply the full render pass to a complete
  string. Used for non-streaming code paths.

* :class:`StreamingRenderer` — incrementally accept text deltas from
  the LLM and emit "speakable chunks" as soon as a sentence boundary
  is hit. Used by the streaming TTS path so we don't wait for the
  full reply before starting to speak.

Pipeline (applied in order):

  1. Drop fenced code blocks (``` ... ```) including their content.
  2. Drop inline code (single backticks).
  3. Strip markdown link syntax but keep the link text: [text](url) -> text.
  4. Drop URLs that stand alone (no surrounding prose).
  5. Remove JSON-looking blocks ({...} or [...]).
  6. Remove leading tool-call prefixes like "Tool call: foo(...)" or
     "Tool result: ..." (configurable patterns).
  7. Collapse multiple blank lines and trailing whitespace.
  8. Normalize whitespace.

The result is a plain string that sounds natural when spoken.
"""

from __future__ import annotations

import re

# Fenced code blocks (``` ... ```).
_FENCED_CODE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
# Inline code (`...`).
_INLINE_CODE = re.compile(r"`[^`\n]+`")
# Markdown link [text](url) -> text.
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# A bare URL (http://, https://, file://...)
_URL = re.compile(r"\b(?:https?|file)://\S+")
# JSON-like blobs. Conservative: only remove if multi-line or curly.
_JSON_LIKE = re.compile(r"(?s)\{[^{}]{20,}\}")
# Tool-call style prefixes the LLM sometimes leaks.
_TOOL_LINE = re.compile(
    r"^\s*(Tool (?:call|result)|Function call|function_call|tool_use)"
    r"\s*[:\-].*$",
    re.IGNORECASE | re.MULTILINE,
)
# Multiple spaces.
_MULTI_SPACE = re.compile(r"[ \t]+")
# Leading list markers at the start of a line.
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)

# Sentence terminators. We use these to know when to flush a chunk.
# Include the colon, semicolon and em-dash so we don't flush too early
# on a list of items like "apples: red; oranges: orange; bananas: yellow."
# We only treat `.`, `!`, `?` followed by whitespace as hard flushes.
_SENTENCE_END = re.compile(r"([.!?])([\s\n]+|$)")


def render_for_speech(text: str) -> str:
    """Return a version of `text` that is suitable to be spoken aloud.

    Strips markdown, code, JSON, and tool-call artifacts; collapses
    whitespace; trims noise. The returned string is plain prose.
    """
    if not text:
        return ""
    s = text
    s = _FENCED_CODE.sub("", s)
    s = _INLINE_CODE.sub("", s)
    s = _MD_LINK.sub(r"\1", s)
    s = _URL.sub("", s)
    s = _JSON_LIKE.sub("", s)
    s = _TOOL_LINE.sub("", s)
    s = _LIST_MARKER.sub("", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = _MULTI_SPACE.sub(" ", s)
    # Strip leading/trailing whitespace per line.
    s = "\n".join(line.strip() for line in s.splitlines())
    return s.strip()


# ---------------------------------------------------------------------------
# Streaming renderer
# ---------------------------------------------------------------------------


class StreamingRenderer:
    """Incrementally convert LLM text deltas into speakable chunks.

    Usage::

        r = StreamingRenderer()
        for delta in llm_deltas:
            for chunk in r.feed(delta):
                tts.synthesize(chunk)
        # At end-of-stream, flush whatever remains.
        last = r.flush()
        if last:
            tts.synthesize(last)

    Sentence boundaries (``.``/``!``/``?`` followed by whitespace or
    end of input) trigger an immediate flush. The renderer also has
    a maximum chunk size so a long run-on sentence (no punctuation)
    still gets spoken incrementally.

    Fenced code blocks (```...```) and inline code (`...`) are kept
    out of the spoken output by simply not emitting any chunk that
    falls entirely inside a code block.
    """

    def __init__(self, max_chunk_chars: int = 240) -> None:
        self._max = max_chunk_chars
        self._buf = ""
        # We track whether we're inside a fenced code block so we can
        # skip over it without speaking the code.
        self._in_code = False

    # -- public --

    def feed(self, delta: str) -> list[str]:
        """Feed new text. Return a list of speakable chunks ready to synthesize.

        Multiple chunks may be returned from a single call (e.g. if the
        delta contained two sentence boundaries). The caller should
        speak them in order.
        """
        if not delta:
            return []
        self._buf += delta
        return self._drain()

    def flush(self) -> str:
        """Return any remaining buffered text (call once at end-of-stream)."""
        rest = self._buf.strip()
        self._buf = ""
        self._in_code = False
        return rest

    # -- internals --

    def _drain(self) -> list[str]:
        out: list[str] = []
        while True:
            chunk = self._extract_one_chunk()
            if chunk is None:
                break
            out.append(chunk)
        return out

    def _extract_one_chunk(self) -> str | None:
        """Find the next speakable chunk in the buffer; return None if
        we need to wait for more input."""
        # First, advance through any code-block transitions so the buffer
        # only contains prose once we start emitting.
        self._advance_past_code_blocks()

        # If we have nothing left after skipping code, wait for more.
        if not self._buf.strip():
            return None

        # Look for a sentence boundary followed by whitespace.
        m = _SENTENCE_END.search(self._buf)
        if m is not None:
            end = m.end()
            chunk = self._buf[:end].strip()
            self._buf = self._buf[end:]
            return render_for_speech(chunk)

        # No sentence boundary yet. If the buffer is large enough, flush
        # the first max_chunk_chars characters to keep latency bounded.
        if len(self._buf) >= self._max:
            # Find the last whitespace before max_chunk to avoid
            # splitting in the middle of a word.
            cut = self._buf.rfind(" ", 0, self._max)
            if cut <= 0:
                cut = self._max
            chunk = self._buf[:cut].strip()
            self._buf = self._buf[cut:]
            return render_for_speech(chunk)

        # Not enough text yet. Wait for more.
        return None

    def _advance_past_code_blocks(self) -> None:
        """Walk through the buffer, treating fenced code blocks as opaque."""
        while True:
            if self._in_code:
                # Look for the closing fence.
                end = self._buf.find("```")
                if end < 0:
                    # No close found yet — drop everything into "code".
                    self._buf = ""
                    return
                # Drop the code (including the closing fence) and resume.
                self._buf = self._buf[end + 3 :]
                self._in_code = False
                continue
            # Look for the next opening fence.
            start = self._buf.find("```")
            if start < 0:
                return
            # Look for a newline (so we don't match across words).
            nl = self._buf.find("\n", start)
            if nl < 0:
                return
            self._in_code = True
            self._buf = self._buf[:start] + self._buf[nl + 1 :]
