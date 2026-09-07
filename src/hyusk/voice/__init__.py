"""Voice interface for Hyusk."""

from hyusk.voice.base import (
    SpeechToText,
    TextToSpeech,
    WakeWordDetector,
    AudioConfig,
    VoiceError,
)
from hyusk.voice.stt import WhisperSTT
from hyusk.voice.tts import KokoroTTS
from hyusk.voice.wakeword import PorcupineWakeWord
from hyusk.voice.audio import AudioInput, AudioOutput

__all__ = [
    "SpeechToText",
    "TextToSpeech",
    "WakeWordDetector",
    "AudioConfig",
    "VoiceError",
    "WhisperSTT",
    "KokoroTTS",
    "PorcupineWakeWord",
    "AudioInput",
    "AudioOutput",
]
