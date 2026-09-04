"""Speech renderer tests (V5)."""

from __future__ import annotations

from hyusk.voice.render import render_for_speech


def test_empty_input():
    assert render_for_speech("") == ""


def test_pure_prose_unchanged():
    text = "Hello, this is a simple sentence without any markup."
    out = render_for_speech(text)
    assert "Hello" in out
    assert "sentence" in out


def test_strips_fenced_code_blocks():
    text = "Sure! I will run that.\n\n```python\ndef hello():\n    print(\"hi\")\n```\n\nLet me know."
    out = render_for_speech(text)
    assert "def hello" not in out
    assert "print" not in out
    assert "Let me know" in out


def test_strips_inline_code():
    # Note: we keep the text inside backticks (ls is preserved)
    text = "Use the `ls` command to list files."
    out = render_for_speech(text)
    assert "`" not in out
    # ls is the text inside backticks - it should still appear
    # (we strip the BACKTICKS, not the content)
    assert "command" in out
    assert "list files" in out


def test_strips_markdown_links_keeps_text():
    text = "See [the docs](https://example.com) for more."
    out = render_for_speech(text)
    assert "https://example.com" not in out
    assert "the docs" in out


def test_strips_urls():
    text = "Visit https://example.com/foo for more info."
    out = render_for_speech(text)
    assert "https://" not in out
    assert "for more info" in out


def test_strips_tool_call_lines():
    text = "I will launch VS Code.\n\nTool call: launch_application(\"VS Code\")\nTool result: launched\n\nDone!"
    out = render_for_speech(text)
    assert "Tool call" not in out
    assert "Tool result" not in out
    assert "launch_application" not in out
    assert "I will launch VS Code" in out
    assert "Done" in out


def test_strips_list_markers():
    text = "Steps:\n- First\n- Second\n- Third\n\nDone."
    out = render_for_speech(text)
    assert "First" in out
    assert "Second" in out
    assert "Third" in out
    assert "- First" not in out


def test_collapses_blank_lines():
    text = "Line 1\n\n\n\nLine 2"
    out = render_for_speech(text)
    # No 3+ consecutive newlines
    assert "\n\n\n" not in out


def test_strips_json_blobs():
    text = "Result: " + "{" + "\"a\": \"b\", " * 30 + "\"end\": true}"
    out = render_for_speech(text)
    assert "Result" in out
    # The big JSON should be gone
    assert "a" not in out.replace("Result", "").replace("\n", "")
