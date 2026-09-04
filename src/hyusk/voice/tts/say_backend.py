"""macOS ``say`` command TTS backend."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger("hyusk.voice.tts.say")


class SayBackend:
    def __init__(self, voice: str = "") -> None:
        self._voice = voice

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
            raise
