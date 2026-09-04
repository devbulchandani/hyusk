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
        # Print is already done by the caller; this is a no-op.
        return
