"""Speech renderer: transform agent output into speakable text.

The agent often returns text with markdown, code blocks, JSON, tool
traces, etc. None of that should be spoken verbatim. This module
removes those non-spoken parts and returns plain prose suitable for
TTS.

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
# Triple backtick line on its own (in case fenced block is unbalanced).
_BLANK_LINES = re.compile(r"\n{3,}")
# Multiple spaces.
_MULTI_SPACE = re.compile(r"[ \t]+")
# Leading list markers at the start of a line.
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)


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
    s = _BLANK_LINES.sub("\n\n", s)
    s = _MULTI_SPACE.sub(" ", s)
    # Strip leading/trailing whitespace per line.
    s = "\n".join(line.strip() for line in s.splitlines())
    return s.strip()
