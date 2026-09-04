"""OpenAI TTS API backend."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile

logger = logging.getLogger("hyusk.voice.tts.openai")


def _api_key() -> str:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY") or ""


def _base_url() -> str:
    return os.environ.get("HYUSK_LLM_BASE_URL") or "https://api.openai.com/v1"


def _player_for_platform() -> str:
    if sys.platform == "darwin":
        return "afplay"
    if sys.platform == "win32":
        return None  # will use winsound below
    return "mpg123"


class OpenAITTSBackend:
    def __init__(self, voice: str = "alloy") -> None:
        self._voice = voice or "alloy"

    def is_available(self) -> bool:
        if not _api_key():
            return False
        try:
            import httpx  # noqa: F401
        except ImportError:
            return False
        return True

    def name(self) -> str:
        return "openai"

    def speak(self, text: str) -> None:
        samples, sr = self.synthesize(text)
        if samples is None or len(samples) == 0:
            return
        try:
            import sounddevice as sd

            sd.play(samples, samplerate=sr)
            sd.wait()
        except Exception as exc:
            logger.warning("OpenAI TTS playback failed: %s", exc)

    def synthesize(self, text: str, voice: str = "", speed=None):
        """Return OpenAI TTS audio as float32 numpy array.

        Requires the API to return PCM directly. Falls back to writing
        to a temp file and decoding via soundfile (pydub optional) if
        only MP3 is available.
        """
        import httpx
        import numpy as np
        import tempfile
        import os

        v = voice or self._voice
        url = _base_url().rstrip("/") + "/audio/speech"
        try:
            # Try PCM response_format (mp3a/wav/pcm) — most endpoints support mp3.
            with httpx.Client(timeout=60) as client:
                r = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {_api_key()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "tts-1",
                        "input": text,
                        "voice": v,
                        # "pcm" gives raw 16-bit little-endian samples we
                        # can decode directly without extra deps.
                        "response_format": "pcm",
                    },
                )
                r.raise_for_status()
                pcm = r.content

            # 24kHz, 16-bit signed little-endian, mono (per OpenAI docs).
            sample_rate = 24000
            audio_int16 = np.frombuffer(pcm, dtype="<i2")
            samples = audio_int16.astype("float32") / 32768.0
            return samples, sample_rate
        except Exception as exc:
            logger.warning("OpenAI TTS synthesize failed: %s", exc)
            raise
