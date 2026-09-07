"""Base classes and interfaces for voice components."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, AsyncIterator
import logging


logger = logging.getLogger(__name__)


class VoiceError(Exception):
    """Base exception for voice-related errors."""

    pass


@dataclass
class AudioConfig:
    """Configuration for audio processing."""

    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    format: str = "int16"

    # STT specific
    language: str = "en"
    model_size: str = "base"  # tiny, base, small, medium, large

    # TTS specific
    voice: str = "default"
    speed: float = 1.0

    # Wake word specific
    sensitivity: float = 0.5
    wake_phrase: str = "hey hyusk"


class SpeechToText(ABC):
    """Abstract base class for speech-to-text engines."""

    def __init__(self, config: AudioConfig):
        self.config = config

    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> str:
        """
        Transcribe audio data to text.

        Args:
            audio_data: Raw audio bytes

        Returns:
            Transcribed text string

        Raises:
            VoiceError: If transcription fails
        """
        pass

    @abstractmethod
    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        Transcribe streaming audio to text.

        Args:
            audio_stream: Async iterator of audio chunks

        Yields:
            Transcribed text chunks

        Raises:
            VoiceError: If transcription fails
        """
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the STT engine and load models."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources."""
        pass


class TextToSpeech(ABC):
    """Abstract base class for text-to-speech engines."""

    def __init__(self, config: AudioConfig):
        self.config = config
        self._is_speaking = False

    @abstractmethod
    async def speak(self, text: str) -> bytes:
        """
        Convert text to speech audio.

        Args:
            text: Text to speak

        Returns:
            Audio data as bytes

        Raises:
            VoiceError: If synthesis fails
        """
        pass

    @abstractmethod
    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream text-to-speech audio.

        Args:
            text: Text to speak

        Yields:
            Audio chunks

        Raises:
            VoiceError: If synthesis fails
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop current speech playback."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the TTS engine and load models."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources."""
        pass

    @property
    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        return self._is_speaking


class WakeWordDetector(ABC):
    """Abstract base class for wake word detection."""

    def __init__(self, config: AudioConfig):
        self.config = config
        self._is_listening = False

    @abstractmethod
    async def wait_for_wake_word(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for wake word detection.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            True if wake word detected, False if timeout

        Raises:
            VoiceError: If detection fails
        """
        pass

    @abstractmethod
    async def start_listening(self) -> None:
        """Start listening for wake word in background."""
        pass

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening for wake word."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the wake word detector."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources."""
        pass

    @property
    def is_listening(self) -> bool:
        """Check if currently listening."""
        return self._is_listening
