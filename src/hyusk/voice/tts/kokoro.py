"""Kokoro TTS backend (local, neural, cross-platform).

Uses the ``kokoro-onnx`` Python package, which wraps the Kokoro ONNX
model. The model runs locally on CPU (and on GPU/CoreML where
available); no cloud dependency.

Installation
------------

::

    uv pip install kokoro-onnx soundfile

Kokoro needs two files on disk: an ONNX model and a voices binary.
On first use, :class:`KokoroBackend` downloads them from HuggingFace
(``onnx-community/Kokoro-82M-v1.0-ONNX``) and caches them under
``~/.cache/hyusk/kokoro/`` (kokoro-v1.0.onnx + voices-v1.0.bin by default). To use a custom path, pass
``kokoro_model`` and ``kokoro_voices`` in the config:

::

    [voice]
    tts_backend = "kokoro"
    tts_voice   = "af_sarah"   # see kokoro\'s voice list
    kokoro_model  = "/path/to/model.onnx"   # optional
    kokoro_voices = "/path/to/voices.bin"   # optional

Default voice: ``af_sarah`` (American English, female).
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hyusk.voice.tts.kokoro")


# Default voice (US English female, good quality, low latency).
DEFAULT_VOICE = "af_sarah"
DEFAULT_SPEED = 1.0

# Kokoro model + voices from the onnx-community v1.0 release.
KOKORO_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
)
KOKORO_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
)
KOKORO_MODEL_DIR = "~/.cache/hyusk/kokoro"


def _ensure_local_model(model_path: str | None, voices_path: str | None) -> tuple[str, str]:
    """Download Kokoro model + voices to a cache dir if not present.

    Returns (model_path, voices_path) ready to pass to Kokoro().
    """
    if model_path and voices_path:
        return model_path, voices_path

    cache_dir = Path(os.path.expanduser(KOKORO_MODEL_DIR))
    cache_dir.mkdir(parents=True, exist_ok=True)

    out_model = model_path or str(cache_dir / "kokoro-v1.0.onnx")
    out_voices = voices_path or str(cache_dir / "voices-v1.0.bin")

    if not Path(out_model).exists():
        logger.info("downloading Kokoro model from %s ...", KOKORO_MODEL_URL)
        urllib.request.urlretrieve(KOKORO_MODEL_URL, out_model + ".part")
        os.rename(out_model + ".part", out_model)
    if not Path(out_voices).exists():
        logger.info("downloading Kokoro voices from %s ...", KOKORO_VOICES_URL)
        urllib.request.urlretrieve(KOKORO_VOICES_URL, out_voices + ".part")
        os.rename(out_voices + ".part", out_voices)
    return out_model, out_voices


class KokoroBackend:
    """Kokoro-onnx TTS backend. Loads the model once and reuses it."""

    def __init__(
        self,
        voice: str = "",
        speed: float = DEFAULT_SPEED,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
    ) -> None:
        self._voice = voice or DEFAULT_VOICE
        self._speed = float(speed) if speed else DEFAULT_SPEED
        self._model_path = model_path or None
        self._voices_path = voices_path or None
        self._kokoro = None  # lazy
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            return True
        except ImportError:
            return False

    def name(self) -> str:
        return "kokoro"

    def _ensure_model(self):
        if self._kokoro is not None:
            return self._kokoro
        with self._lock:
            if self._kokoro is not None:
                return self._kokoro
            import kokoro_onnx
            try:
                mp, vp = _ensure_local_model(self._model_path, self._voices_path)
                self._kokoro = kokoro_onnx.Kokoro(mp, vp)
            except Exception as exc:
                logger.warning("failed to load Kokoro model: %s", exc)
                raise
        return self._kokoro

    def synthesize(self, text: str, voice: str = "", speed: Optional[float] = None):
        k = self._ensure_model()
        v = voice or self._voice
        s = float(speed) if speed else self._speed
        try:
            result = k.create(text, voice=v, speed=s)
            if isinstance(result, tuple) and len(result) == 2:
                samples, sr = result
                return samples, sr
            return result, 24000
        except Exception as exc:
            logger.warning("kokoro create() failed: %s", exc)
            raise

    def speak(self, text: str) -> None:
        try:
            samples, sr = self.synthesize(text)
        except Exception:
            return
        try:
            import sounddevice as sd
            sd.play(samples.astype("float32"), samplerate=sr)
            sd.wait()
        except Exception as exc:
            logger.warning("kokoro playback failed: %s", exc)
