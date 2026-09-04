"""No STT — the caller reads from stdin instead. Useful for
headless / CI environments and as a safe fallback when no STT backend
is available."""

from __future__ import annotations


class TextBackend:
    def is_available(self) -> bool:
        return True

    def name(self) -> str:
        return "text"

    def transcribe(self, audio_path: str) -> str:  # noqa: ARG002
        return ""
