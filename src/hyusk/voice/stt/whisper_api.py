"""OpenAI Whisper API backend (cloud)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("hyusk.voice.stt.whisper_api")


def _api_key() -> str:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY") or ""


def _base_url() -> str:
    return os.environ.get("HYUSK_LLM_BASE_URL") or "https://api.openai.com/v1"


class WhisperAPI:
    def is_available(self) -> bool:
        if not _api_key():
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def name(self) -> str:
        return "whisper-api"

    def transcribe(self, audio_path: str) -> str:
        try:
            from openai import OpenAI

            api_key = _api_key()
            base_url = _base_url()
            client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            with open(audio_path, "rb") as f:
                resp = client.audio.transcriptions.create(model="whisper-1", file=f)
            return getattr(resp, "text", "") or ""
        except Exception as exc:
            logger.warning("Whisper API failed: %s", exc)
            return ""
