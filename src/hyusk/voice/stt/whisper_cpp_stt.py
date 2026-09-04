"""whisper.cpp STT backend (local, cross-platform).

Uses the ``pywhispercpp`` Python wrapper around the whisper.cpp C++
implementation. Models are auto-downloaded on first use to
``~/.cache/huggingface/hub`` (or wherever pywhispercpp puts them).

Supported models (passed as the ``voice.whisper_model`` config value
or the ``HYUSK_WHISPER_MODEL`` env var):

  * ``tiny``        (39M,  fastest)  — recommended for low-latency
  * ``tiny.en``     (39M,  English-only, fastest)
  * ``base``        (74M,  good default)
  * ``base.en``     (74M,  English-only, recommended for Hyusk)
  * ``small``       (244M, more accurate)
  * ``small.en``    (244M, English-only, more accurate)
  * ``medium``      (769M, slow)
  * ``large-v3``    (1550M, very slow)

The model is loaded **once** and reused across utterances.

Installation
------------

::

    uv pip install pywhispercpp
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("hyusk.voice.stt.whisper_cpp")


# Default model — small, English-only, fast enough for real-time.
DEFAULT_MODEL = "base.en"
DEFAULT_LANGUAGE = "en"
DEFAULT_N_THREADS = 0  # 0 = auto


class WhisperCppSTT:
    """STT via pywhispercpp (whisper.cpp)."""

    def __init__(
        self,
        model: str = "",
        language: str = DEFAULT_LANGUAGE,
        n_threads: int = DEFAULT_N_THREADS,
    ) -> None:
        self._model_name = model or os.environ.get("HYUSK_WHISPER_MODEL") or DEFAULT_MODEL
        self._language = language or DEFAULT_LANGUAGE
        self._n_threads = n_threads or DEFAULT_N_THREADS
        self._model = None  # lazy
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        try:
            import pywhispercpp.model  # noqa: F401
            return True
        except ImportError:
            return False

    def name(self) -> str:
        return "whisper_cpp"

    # -- internal --

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            # NOTE: do NOT pass ContextParams here — it triggers a known
            # "vector" exception in pywhispercpp 1.5.x with numpy 1.26+.
            # The language is passed at transcribe() time instead.
            from pywhispercpp.model import Model

            logger.info("loading whisper.cpp model %r ...", self._model_name)
            try:
                # NOTE: do NOT pass `redirect_whispercpp_logs_to=None` — that
                # triggers a "vector" exception in pywhispercpp 1.5.x with
                # numpy 1.26+. We rely on the default (False) which silences
                # whisper.cpp's C-level stderr output.
                self._model = Model(
                    self._model_name,
                    print_progress=False,
                    n_threads=self._n_threads,
                )
            except Exception as exc:
                logger.warning("failed to load whisper.cpp model %r: %s", self._model_name, exc)
                raise
        return self._model

    # -- public API --

    def transcribe(self, audio_path: str) -> str:
        try:
            model = self._ensure_model()
            # Pass language as a kwarg; using ContextParams in the
            # constructor triggers a "vector" exception in pywhispercpp 1.5.x.
            result = model.transcribe(audio_path, language=self._language)
            # pywhispercpp returns either a list of segments or a string
            # depending on the version. Normalize to a string.
            if isinstance(result, list):
                return " ".join(
                    getattr(seg, "text", str(seg)) for seg in result
                ).strip()
            if isinstance(result, str):
                return result.strip()
            # Some versions return a dict-like object.
            return str(result).strip()
        except Exception as exc:
            logger.warning("whisper.cpp transcription failed: %s", exc)
            return ""
