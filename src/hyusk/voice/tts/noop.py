"""No-op TTS backend. Just prints the reply text (the voice client
already prints it)."""

from __future__ import annotations

import logging

logger = logging.getLogger("hyusk.voice.tts.noop")


class NoOpBackend:
    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "none"

    def speak(self, text: str) -> None:  # noqa: ARG002
        return

    def synthesize(self, text: str, voice: str = "", speed=None):  # noqa: ARG002
        """Return an empty audio buffer (no sound)."""
        import numpy as np
        return np.zeros((0,), dtype="float32"), 24000
