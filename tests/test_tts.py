"""TTS backend selection tests (V4.1)."""

from __future__ import annotations

import sys

from hyusk.voice import tts


def test_noop_backend_is_always_available():
    b = tts.NoOpBackend()
    assert b.is_available()
    assert b.name() == "none"
    # speak() should be a no-op (no exception).
    b.speak("hello")


def test_say_backend_only_available_on_macos():
    b = tts.SayBackend()
    if sys.platform == "darwin":
        # On a real Mac with /usr/bin/say, this is available.
        # We don't assert is_available() strictly because CI may be a stripped image.
        assert b.name() == "say"
    else:
        assert not b.is_available()


def test_select_backend_none():
    b = tts.select_backend(tts.TTSConfig(backend="none"))
    assert b.name() == "none"
    assert b.is_available()


def test_select_backend_unknown_falls_back_to_none():
    b = tts.select_backend(tts.TTSConfig(backend="does-not-exist"))
    assert b.name() == "none"


def test_select_backend_say_respects_platform():
    b = tts.select_backend(tts.TTSConfig(backend="say"))
    if sys.platform == "darwin":
        # On macOS the backend may or may not be available depending on
        # whether /usr/bin/say is in PATH (it should be). We just check
        # the type, not availability, because CI images vary.
        assert b.name() == "say"
    else:
        # On other platforms, say is unavailable, so we fall back to none.
        assert b.name() == "none"


def test_select_backend_kitten_when_unavailable_falls_back():
    """Without `kittentts` installed, kitten should fall back to none."""
    b = tts.select_backend(tts.TTSConfig(backend="kitten"))
    if not b.is_available():
        assert b.name() == "none"
    # If it IS available, the name should be "kitten".


def test_say_backend_speak_invokes_subprocess(monkeypatch):
    """The Say backend should call the `say` command with the text."""
    import subprocess

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = tts.SayBackend(voice="Daniel")
    b.speak("hello world")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "say"
    assert "-v" in cmd
    assert "Daniel" in cmd
    assert "hello world" in cmd


def test_say_backend_omits_voice_flag_when_unset(monkeypatch):
    """If no voice is set, the -v flag should not be passed."""
    import subprocess

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = tts.SayBackend(voice="")
    b.speak("hi")
    assert calls == [["say", "hi"]]
