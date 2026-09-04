"""Text-to-speech backends (V4.1).

The voice client picks a backend based on the user's config
(`voice.tts_backend` in `~/.config/hyusk/config.toml`). Default: `say`
on macOS (zero deps).

Backends
--------

`say`           macOS built-in. Always available on macOS. Voices like
                Samantha, Daniel, Karen. Decent quality. Subprocess
                call to `/usr/bin/say`.

`kitten`        KittenTTS (kittenml/KittenTTS on GitHub). Small (~25MB),
                local, open-weights, good quality. Optional dependency:
                `uv pip install kittentts`.

`openai`        OpenAI TTS API. Cloud. Best quality, many voices. Needs
                an OPENAI_API_KEY. Optional dependency: `uv pip install openai`.

`none`          No TTS — just print the reply.

If the chosen backend is unavailable, the client logs a warning and
falls back to `none`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("hyusk.voice.tts")


@dataclass
class TTSConfig:
    backend: str = ""     # empty = use the default from user config
    voice: str = ""       # backend-specific voice name
    openai_voice: str = "alloy"  # OpenAI TTS voice


class TTSBackend(Protocol):
    def speak(self, text: str) -> None: ...
    def is_available(self) -> bool: ...
    def name(self) -> str: ...


class SayBackend:
    """macOS `say` command."""

    def is_available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("say") is not None

    def name(self) -> str:
        return "say"

    def speak(self, text: str) -> None:
        cmd = ["say"]
        if self._voice:
            cmd += ["-v", self._voice]
        cmd += [text]
        try:
            subprocess.run(cmd, check=False, timeout=30)
        except Exception as exc:
            logger.warning("`say` failed: %s", exc)

    def __init__(self, voice: str = "") -> None:
        self._voice = voice


class KittenBackend:
    """KittenTTS (local, open-weights, ~25MB)."""

    def is_available(self) -> bool:
        try:
            import kittentts  # noqa: F401
            return True
        except ImportError:
            return False

    def name(self) -> str:
        return "kitten"

    def __init__(self, voice: str = "") -> None:
        self._voice = voice
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from kittentts import KittenTTS

                # The first model load takes a few seconds; we do it once.
                self._model = KittenTTS("KittenML/kitten-tts-nano-0.1")
            except Exception as exc:
                logger.warning("failed to load KittenTTS: %s", exc)
                raise
        return self._model

    def speak(self, text: str) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            logger.warning("KittenTTS needs sounddevice + numpy: %s", exc)
            return
        try:
            model = self._load()
            audio = model.generate(text, voice=self._voice or "expr-voice-2-m")
            sd.play(audio, samplerate=24000)
            sd.wait()
        except Exception as exc:
            logger.warning("KittenTTS playback failed: %s", exc)


class OpenAITTSBackend:
    """OpenAI TTS API."""

    def is_available(self) -> bool:
        # We need either an API key in env or in user config.
        return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY"))

    def name(self) -> str:
        return "openai"

    def __init__(self, voice: str = "alloy") -> None:
        self._voice = voice or "alloy"

    def speak(self, text: str) -> None:
        try:
            import httpx
        except ImportError:
            logger.warning("OpenAI TTS needs httpx: `uv pip install httpx`")
            return
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY")
        base_url = os.environ.get("HYUSK_LLM_BASE_URL") or "https://api.openai.com/v1"
        url = base_url.rstrip("/") + "/audio/speech"
        try:
            with httpx.Client(timeout=60) as client:
                r = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "tts-1",
                        "input": text,
                        "voice": self._voice,
                    },
                )
                r.raise_for_status()
                # Save to a temp file and play with afplay (macOS).
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(r.content)
                    tmp_path = f.name
            try:
                subprocess.run(["afplay", tmp_path], check=False, timeout=60)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("OpenAI TTS failed: %s", exc)


class NoOpBackend:
    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "none"

    def speak(self, text: str) -> None:  # noqa: ARG002
        # Print is already done by the caller; this is a no-op.
        return


def _default_backend_name() -> str:
    """Pick a sensible default for the current platform."""
    if sys.platform == "darwin":
        return "say"
    return "none"


def select_backend(cfg: TTSConfig) -> TTSBackend:
    """Pick the TTS backend based on config and availability."""
    name = (cfg.backend or "").strip().lower()
    if not name:
        name = _default_backend_name()

    b: TTSBackend
    if name == "say":
        b = SayBackend(voice=cfg.voice)
    elif name == "kitten":
        b = KittenBackend(voice=cfg.voice)
    elif name == "openai":
        b = OpenAITTSBackend(voice=cfg.openai_voice)
    elif name in ("none", "off", "false"):
        return NoOpBackend()
    else:
        logger.warning("unknown TTS backend %r; falling back to none", name)
        return NoOpBackend()

    if not b.is_available():
        logger.warning("TTS backend %r is not available; using none", b.name())
        return NoOpBackend()
    return b
