"""Text-to-speech backends for the Hyusk voice client.

All backends implement the :class:`TTSBackend` Protocol. The agent core
only depends on this Protocol — it has no knowledge of Kokoro, `say`,
or any other concrete provider.

The default TTS is configurable via ``hyusk config set voice.tts_backend <name>``:

  * ``none``     no TTS — replies are printed only
  * ``say``      macOS built-in ``say`` command
  * ``kokoro``   local neural TTS via ``kokoro-onnx`` (recommended)
  * ``openai``   OpenAI TTS API (cloud)

Additional per-backend options (voice, speed, model path) are read from
``~/.config/hyusk/config.toml`` under the ``[voice]`` section.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("hyusk.voice.tts")


@dataclass
class TTSConfig:
    backend: str = ""            # empty = use the default from user config
    voice: str = ""              # backend-specific voice name
    speed: float = 1.0           # speech rate multiplier
    openai_voice: str = "alloy"  # OpenAI TTS voice
    kokoro_model: str = ""       # path to Kokoro onnx model (optional)
    kokoro_voices: str = ""      # path to Kokoro voices bin (optional)


class TTSBackend(Protocol):
    """A text-to-speech provider."""

    def speak(self, text: str) -> None:
        """Synthesize and play `text`. May raise on hard failure."""
        ...

    def is_available(self) -> bool:
        """Whether the backend can run on this machine right now."""
        ...

    def name(self) -> str:
        """Human-readable backend name (used in config and logs)."""
        ...


# Re-export the concrete backends for convenient imports.
from .noop import NoOpBackend          # noqa: F401
from .say_backend import SayBackend   # noqa: F401
from .kokoro import KokoroBackend       # noqa: F401
from .openai_tts import OpenAITTSBackend  # noqa: F401


def _default_backend_name() -> str:
    """Pick a sensible default for the current platform."""
    import sys

    if sys.platform == "darwin":
        return "say"
    return "none"


def select_backend(cfg: TTSConfig) -> "TTSBackend":
    """Pick a TTS backend based on config and availability.

    Falls back to :class:`NoOpBackend` if the requested backend is not
    available; never raises.
    """
    name = (cfg.backend or "").strip().lower()
    if not name:
        name = _default_backend_name()

    if name in ("none", "off", "false"):
        return NoOpBackend()
    if name == "say":
        b: TTSBackend = SayBackend(voice=cfg.voice)
    elif name == "kokoro":
        b = KokoroBackend(
            voice=cfg.voice,
            speed=cfg.speed,
            model_path=cfg.kokoro_model or None,
            voices_path=cfg.kokoro_voices or None,
        )
    elif name == "openai":
        b = OpenAITTSBackend(voice=cfg.openai_voice)
    else:
        logger.warning("unknown TTS backend %r; using none", name)
        return NoOpBackend()

    if not b.is_available():
        logger.warning("TTS backend %r is not available; using none", b.name())
        return NoOpBackend()
    return b


__all__ = [
    "TTSBackend",
    "TTSConfig",
    "select_backend",
    "NoOpBackend",
    "SayBackend",
    "KokoroBackend",
    "OpenAITTSBackend",
]
