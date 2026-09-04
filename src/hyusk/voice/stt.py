"""Speech-to-text backends (V4.1).

The voice client uses STT to transcribe microphone input into text
that it then sends to the daemon as a regular `run` message.

Backends
--------

`mlx-whisper`   Apple-Silicon-native Whisper. Very fast on M1/M2/M3.
                Optional dep: `uv pip install mlx-whisper`. Falls back to
                `openai-whisper` if mlx-whisper is unavailable.

`openai-whisper` Cross-platform Whisper. CPU and GPU support. Optional
                dep: `uv pip install openai-whisper`.

`whisper-api`   OpenAI Whisper API (cloud). Needs OPENAI_API_KEY.
                Optional dep: `uv pip install openai`.

`text`          No STT. The client reads from stdin. This is the default
                in headless / CI environments.

If no STT backend is available, the client falls back to `text`.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Protocol

logger = logging.getLogger("hyusk.voice.stt")


class STTBackend(Protocol):
    def transcribe(self, audio_path: str) -> str: ...
    def is_available(self) -> bool: ...
    def name(self) -> str: ...


class TextBackend:
    """No STT — the caller reads from stdin instead."""

    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "text"

    def transcribe(self, audio_path: str) -> str:  # noqa: ARG002
        return ""


class WhisperAPI:
    def is_available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY"))

    def name(self) -> str:
        return "whisper-api"

    def transcribe(self, audio_path: str) -> str:
        try:
            from openai import OpenAI

            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY")
            base_url = os.environ.get("HYUSK_LLM_BASE_URL")
            client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            with open(audio_path, "rb") as f:
                resp = client.audio.transcriptions.create(model="whisper-1", file=f)
            return getattr(resp, "text", "") or ""
        except Exception as exc:
            logger.warning("Whisper API failed: %s", exc)
            return ""


class LocalWhisper:
    """Local Whisper via mlx-whisper (macOS) or openai-whisper (other)."""

    def __init__(self) -> None:
        self._backend: str | None = None

    def is_available(self) -> bool:
        if self._backend is not None:
            return self._backend != ""
        if sys.platform == "darwin":
            try:
                import mlx_whisper  # noqa: F401
                self._backend = "mlx"
                return True
            except ImportError:
                pass
        try:
            import whisper  # noqa: F401
            self._backend = "openai"
            return True
        except ImportError:
            self._backend = ""
            return False

    def name(self) -> str:
        return f"local-whisper ({self._backend or 'none'})"

    def transcribe(self, audio_path: str) -> str:
        try:
            if self._backend == "mlx":
                import mlx_whisper

                result = mlx_whisper.transcribe(audio_path, path_or_hf_repo="mlx-community/whisper-tiny")
                return result.get("text", "") or ""
            if self._backend == "openai":
                import whisper

                model = whisper.load_model("tiny")
                result = model.transcribe(audio_path)
                return result.get("text", "") or ""
        except Exception as exc:
            logger.warning("local whisper failed: %s", exc)
        return ""


def _default_backend_name() -> str:
    if sys.platform == "darwin":
        return "mlx-whisper"
    return "whisper-api"


def select_backend(name: str = "") -> STTBackend:
    n = (name or "").strip().lower()
    if not n:
        n = _default_backend_name()

    if n in ("text", "stdin", "none"):
        return TextBackend()
    b: STTBackend
    if n in ("whisper-api", "openai"):
        b = WhisperAPI()
    elif n in ("mlx-whisper", "local", "local-whisper"):
        b = LocalWhisper()
    else:
        logger.warning("unknown STT backend %r; falling back to text", n)
        return TextBackend()

    if not b.is_available():
        logger.warning("STT backend %r is not available; using text", b.name())
        return TextBackend()
    return b
