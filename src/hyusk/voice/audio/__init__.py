"""Platform-agnostic audio I/O for the voice client.

The :class:`AudioInput` and :class:`AudioOutput` protocols describe the
behaviour the rest of Hyusk expects. The default implementation
(:class:`SoundDeviceAudio`) uses the cross-platform ``sounddevice``
library and works on macOS, Linux, and Windows.

Custom implementations can be plugged in (e.g. for a mobile client using
the system audio APIs directly), but the default works everywhere
``sounddevice`` is installed.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Protocol

import numpy as np

logger = logging.getLogger("hyusk.voice.audio")


SAMPLE_RATE_DEFAULT = 16000
CHANNELS_DEFAULT = 1


class AudioInput(Protocol):
    """Record audio from a microphone."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def read_chunk(self, samples: int) -> "np.ndarray": ...
    @property
    def sample_rate(self) -> int: ...
    @property
    def channels(self) -> int: ...
    def list_devices(self) -> list[dict]: ...


class AudioOutput(Protocol):
    """Play audio to a speaker."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def play(self, audio: "np.ndarray", sample_rate: int) -> None: ...


class SoundDeviceAudio:
    """Default implementation backed by ``sounddevice``."""

    def __init__(self) -> None:
        self._input_stream = None
        self._output_stream = None
        self._sample_rate = SAMPLE_RATE_DEFAULT
        self._channels = CHANNELS_DEFAULT
        self._lock = threading.Lock()

    # --- Input ---

    def open(self) -> None:
        with self._lock:
            if self._input_stream is None:
                import sounddevice as sd

                self._input_stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="float32",
                )

    def close(self) -> None:
        with self._lock:
            if self._input_stream is not None:
                try:
                    self._input_stream.close()
                except Exception:
                    pass
                self._input_stream = None

    def read_chunk(self, samples: int) -> "np.ndarray":
        if self._input_stream is None:
            self.open()
        chunk, _ = self._input_stream.read(samples)
        return chunk.copy()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def list_devices(self) -> list[dict]:
        try:
            import sounddevice as sd

            return list(sd.query_devices())
        except Exception as exc:
            logger.warning("list_devices failed: %s", exc)
            return []

    # --- Output ---

    def play(self, audio: "np.ndarray", sample_rate: int) -> None:
        try:
            import sounddevice as sd

            sd.play(audio, samplerate=sample_rate)
            sd.wait()
        except Exception as exc:
            logger.warning("audio playback failed: %s", exc)
            raise


def rms(chunk: "np.ndarray") -> float:
    """Root-mean-square amplitude of a chunk."""
    if len(chunk) == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk * chunk)))


def is_speech(chunk: "np.ndarray", threshold: float) -> bool:
    """Energy-based speech detection."""
    return rms(chunk) > threshold


def level_bar(rms_value: float, width: int = 20) -> str:
    """Tiny ASCII level meter for live feedback."""
    fill = min(width, int(rms_value * width * 10))
    return "[" + "\u2588" * fill + "\u00b7" * (width - fill) + "]"
