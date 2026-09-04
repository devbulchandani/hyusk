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
        import httpx

        url = _base_url().rstrip("/") + "/audio/speech"
        try:
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
                        "voice": self._voice,
                    },
                )
                r.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(r.content)
                    tmp_path = f.name
        except Exception as exc:
            logger.warning("OpenAI TTS request failed: %s", exc)
            raise

        # Play using a platform-appropriate player.
        try:
            player = _player_for_platform()
            if player is None:
                # Windows: use the PowerShell MediaPlayer.
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(New-Object Media.SoundPlayer \"{tmp_path}\").PlaySync()",
                    ],
                    check=False,
                    timeout=60,
                )
            else:
                subprocess.run([player, tmp_path], check=False, timeout=60)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
