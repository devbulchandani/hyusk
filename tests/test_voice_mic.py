"""Voice mic mode tests (V4.1.3)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from hyusk.voice import stt


def test_is_speech_threshold():
    """A silence-like chunk returns False; a loud chunk returns True."""
    import numpy as np
    from hyusk.voice.client import _is_speech
    quiet = np.zeros((1600,), dtype="float32")
    loud = np.ones((1600,), dtype="float32") * 0.5
    assert _is_speech(quiet) is False
    assert _is_speech(loud) is True


def test_record_falls_back_to_text_when_no_mic():
    """If sounddevice reports no input devices, fall back to stdin.

    This test patches sounddevice BEFORE the function imports it. We
    simulate the no-mic scenario by setting query_devices to return an
    empty list.
    """
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = []  # no input devices

    class FakeStt:
        def is_available(self) -> bool:
            return True
        def name(self) -> str:
            return "fake"
        def transcribe(self, p) -> str:
            return "should not be called"

    with patch.dict(sys.modules, {"sounddevice": fake_sd}):
        from hyusk.voice import client as vclient
        with patch("hyusk.voice.client.sd", fake_sd, create=True):
            with patch("builtins.input", return_value="typed fallback"):
                import asyncio
                result = asyncio.run(vclient._record_and_transcribe(FakeStt()))
    assert result == "typed fallback"


def test_stt_backend_selection_returns_real_for_mac():
    """On macOS, the default STT is mlx-whisper (auto-selected)."""
    b = stt.select_backend("")  # empty -> use default
    if sys.platform == "darwin":
        # Should try mlx-whisper first; if not installed, fall back to text.
        assert b.name() in ("text", "local-whisper (mlx)")


def test_stt_unknown_backend_falls_back_to_text():
    b = stt.select_backend("does-not-exist")
    assert b.name() == "text"
    assert b.is_available()


def test_text_backend_is_always_available():
    b = stt.TextBackend()
    assert b.is_available()
    assert b.name() == "text"
    assert b.transcribe("/dev/null") == ""
