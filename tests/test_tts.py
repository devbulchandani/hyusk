"""TTS backend tests (V5: Kokoro, Say, OpenAI, NoOp)."""

from __future__ import annotations

import sys

from hyusk.voice import tts
from hyusk.voice.tts import (
    TTSConfig,
    NoOpBackend,
    SayBackend,
    KokoroBackend,
    OpenAITTSBackend,
)


def test_noop_backend_is_always_available():
    b = NoOpBackend()
    assert b.is_available()
    assert b.name() == "none"
    b.speak("hello")


def test_say_backend_only_available_on_macos():
    b = SayBackend()
    if sys.platform == "darwin":
        assert b.name() == "say"
    else:
        assert not b.is_available()


def test_kokoro_backend_imports_cleanly():
    b = KokoroBackend()
    assert b.name() == "kokoro"
    assert isinstance(b.is_available(), bool)


def test_openai_backend_requires_api_key():
    b = OpenAITTSBackend(voice="alloy")
    import os
    has_key = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY")
    )
    assert b.is_available() == has_key


def test_select_backend_none():
    b = tts.select_backend(TTSConfig(backend="none"))
    assert b.name() == "none"
    assert b.is_available()


def test_select_backend_unknown_falls_back_to_none():
    b = tts.select_backend(TTSConfig(backend="does-not-exist"))
    assert b.name() == "none"


def test_select_backend_say_respects_platform():
    b = tts.select_backend(TTSConfig(backend="say"))
    if sys.platform == "darwin":
        assert b.name() == "say"
    else:
        assert b.name() == "none"


def test_say_backend_speak_invokes_subprocess(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = SayBackend(voice="Daniel")
    b.speak("hello world")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "say"
    assert "-v" in cmd
    assert "Daniel" in cmd
    assert "hello world" in cmd


def test_say_backend_omits_voice_flag_when_unset(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = SayBackend(voice="")
    b.speak("hi")
    assert calls == [["say", "hi"]]


def test_kokoro_config_defaults():
    b = KokoroBackend()
    assert b._voice
    assert b._speed > 0


def test_tts_config_dataclass():
    c = TTSConfig()
    assert c.backend == ""
    assert c.voice == ""
    assert c.speed == 1.0
    c2 = TTSConfig(backend="kokoro", voice="af_sarah", speed=1.2)
    assert c2.backend == "kokoro"
    assert c2.voice == "af_sarah"
    assert c2.speed == 1.2
