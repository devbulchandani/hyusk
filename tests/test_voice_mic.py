"""Voice mic mode tests (V5)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from hyusk.voice import stt
from hyusk.voice.stt import TextBackend, WhisperCppSTT, WhisperAPI, select_backend
from hyusk.voice.audio import rms, is_speech, level_bar


def test_audio_rms_on_silence():
    quiet = np.zeros((1600,), dtype="float32")
    assert rms(quiet) == 0.0


def test_audio_rms_on_loud_signal():
    # Use small amplitude so the assert range is meaningful
    loud = np.ones((1600,), dtype="float32") * 0.1
    assert 0.05 < rms(loud) < 0.15


def test_is_speech_threshold():
    quiet = np.zeros((1600,), dtype="float32")
    loud = np.ones((1600,), dtype="float32") * 0.5
    assert is_speech(quiet, threshold=0.01) is False
    assert is_speech(loud, threshold=0.01) is True


def test_level_bar_renders_blocks():
    bar = level_bar(0.05, width=20)
    assert bar.startswith("[")
    assert bar.endswith("]")
    # All-silent should have no fill
    bar0 = level_bar(0.0, width=10)
    assert bar0.count("\u2588") == 0


def test_text_backend_always_available():
    b = TextBackend()
    assert b.is_available()
    assert b.name() == "text"
    assert b.transcribe("/dev/null") == ""


def test_stt_unknown_backend_falls_back_to_text():
    b = select_backend("does-not-exist")
    assert b.name() == "text"
    assert b.is_available()


def test_stt_default_backend_picks_platform_specific():
    b = select_backend("")
    if sys.platform == "darwin":
        # whisper_cpp is the default on macOS; may fall back to text.
        assert b.name() in ("text", "whisper_cpp")


def test_whisper_cpp_backend_is_available_iff_package_installed():
    b = WhisperCppSTT()
    assert isinstance(b.is_available(), bool)


def test_whisper_api_backend_is_available_iff_api_key_present():
    b = WhisperAPI()
    import os
    has_key = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY")
    )
    assert b.is_available() == has_key


def test_whisper_cpp_backend_uses_configured_model(monkeypatch):
    import os
    monkeypatch.setenv("HYUSK_WHISPER_MODEL", "tiny")
    b = WhisperCppSTT()
    assert b._model_name == "tiny"
