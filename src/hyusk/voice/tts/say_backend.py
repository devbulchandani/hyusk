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

    def synthesize(self, text: str, voice: str = "", speed=None):
        """Use ``say`` to render to an AIFF file, then return the samples.

        This is a best-effort path so the streaming TTS can use ``say``
        on macOS. We pipe ``say`` into an aiff file and read it back
        with ``scipy.io.wavfile``. Returns ``(samples, 22050)``.
        """
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        if not text.strip():
            import numpy as np
            return np.zeros((0,), dtype="float32"), 22050

        v = voice or self._voice
        try:
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
                out_path = f.name
            cmd = ["say", "-o", out_path]
            if v:
                cmd += ["-v", v]
            cmd += [text]
            subprocess.run(cmd, check=True, timeout=30)
            try:
                import scipy.io.wavfile as wav

                sample_rate, data = wav.read(out_path)
                # Convert int16 to float32 in [-1, 1]
                if data.dtype == "int16":
                    import numpy as np
                    samples = data.astype("float32") / 32768.0
                else:
                    samples = data.astype("float32")
                return samples, int(sample_rate)
            finally:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning("`say` synthesize failed: %s", exc)
            raise
