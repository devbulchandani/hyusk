"""Speech-to-text backends for the Hyusk voice client.

All backends implement the :class:`STTBackend` Protocol. The agent core
only knows about this Protocol.

Configured via ``hyusk config set voice.stt_backend <name>``:

  * ``text``         no STT — read from stdin
  * ``whisper_cpp``  local Whisper via pywhispercpp (recommended)
  * ``whisper_api``  OpenAI Whisper API (cloud)

Per-backend settings (model, language) live in the ``[voice]`` section
of the user config.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

logger = logging.getLogger("hyusk.voice.stt")


class STTBackend(Protocol):
    """A speech-to-text provider."""

    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file at `audio_path` and return the text."""
        ...

    def is_available(self) -> bool:
        """Whether this backend can run on this machine right now."""
        ...

    def name(self) -> str:
        """Human-readable backend name."""
        ...


# Re-export the concrete backends.
from .text_backend import TextBackend                # noqa: F401
from .whisper_cpp_stt import WhisperCppSTT            # noqa: F401
from .whisper_api import WhisperAPI                  # noqa: F401


def _default_backend_name() -> str:
    """Pick a sensible default STT backend for this platform."""
    if sys.platform == "darwin":
        return "whisper_cpp"
    return "whisper_api"


def select_backend(name: str = "") -> "STTBackend":
    """Pick an STT backend by name, falling back to ``text`` if unavailable.

    Recognized names: ``text``, ``stdin``, ``whisper_cpp``,
    ``whisper``, ``whisper_api``, ``openai``. Unknown names are mapped to
    ``text`` with a warning.
    """
    n = (name or "").strip().lower()
    if not n:
        n = _default_backend_name()

    if n in ("text", "stdin", "none"):
        return TextBackend()
    if n in ("whisper_cpp", "whisper", "whisper.cpp"):
        b: STTBackend = WhisperCppSTT()
    elif n in ("whisper_api", "openai"):
        b = WhisperAPI()
    else:
        logger.warning("unknown STT backend %r; using text", n)
        return TextBackend()

    if not b.is_available():
        logger.warning("STT backend %r is not available; using text", b.name())
        return TextBackend()
    return b


__all__ = [
    "STTBackend",
    "select_backend",
    "TextBackend",
    "WhisperCppSTT",
    "WhisperAPI",
]
