"""Speech-to-text implementation using Whisper."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, AsyncIterator

try:
    import whisper
    
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

from hyusk.voice.base import SpeechToText, AudioConfig, VoiceError

logger = logging.getLogger(__name__)


class WhisperSTT(SpeechToText):
    """Speech-to-text using OpenAI Whisper."""

    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self._model: Optional[whisper.Whisper] = None
        self._model_name = config.model_size

    async def initialize(self) -> None:
        """Load Whisper model."""
        if not WHISPER_AVAILABLE:
            raise VoiceError(
                "Whisper not available. Install with: pip install openai-whisper"
            )

        logger.info(f"Loading Whisper model: {self._model_name}")

        try:
            # Load model in executor to avoid blocking
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None, whisper.load_model, self._model_name
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            raise VoiceError(f"Failed to load Whisper model: {e}")

    async def transcribe(self, audio_data: bytes) -> str:
        """
        Transcribe audio data to text.

        Args:
            audio_data: Raw audio bytes (16-bit PCM)

        Returns:
            Transcribed text

        Raises:
            VoiceError: If transcription fails
        """
        if not self._model:
            raise VoiceError("Whisper model not initialized")

        # Whisper expects a file or numpy array
        # Save to temp file for simplicity
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = Path(f.name)

                # Write WAV header + data
                import wave

                with wave.open(str(temp_path), "wb") as wf:
                    wf.setnchannels(self.config.channels)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(self.config.sample_rate)
                    wf.writeframes(audio_data)

            # Transcribe in executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(
                    str(temp_path), language=self.config.language
                ),
            )

            text = result["text"].strip()
            logger.info(f"Transcribed: {text}")
            return text

        except Exception as e:
            raise VoiceError(f"Transcription failed: {e}")
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()

    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        Transcribe streaming audio.

        Note: Whisper doesn't support true streaming, so we accumulate
        chunks and transcribe periodically.

        Args:
            audio_stream: Audio chunks

        Yields:
            Transcribed text segments
        """
        if not self._model:
            raise VoiceError("Whisper model not initialized")

        buffer = bytearray()
        chunk_duration = 3.0  # Transcribe every 3 seconds
        bytes_per_second = self.config.sample_rate * self.config.channels * 2  # 16-bit
        chunk_size = int(bytes_per_second * chunk_duration)

        try:
            async for chunk in audio_stream:
                buffer.extend(chunk)

                # Transcribe when we have enough data
                if len(buffer) >= chunk_size:
                    text = await self.transcribe(bytes(buffer))
                    if text:
                        yield text
                    buffer.clear()

            # Transcribe any remaining data
            if buffer:
                text = await self.transcribe(bytes(buffer))
                if text:
                    yield text

        except Exception as e:
            raise VoiceError(f"Stream transcription failed: {e}")

    async def cleanup(self) -> None:
        """Clean up resources."""
        self._model = None
        logger.info("Whisper STT cleaned up")


class WhisperCppSTT(SpeechToText):
    """
    Speech-to-text using whisper.cpp.

    This is a placeholder for future whisper.cpp integration.
    whisper.cpp provides faster inference and streaming support.
    """

    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self._model_path: Optional[Path] = None

    async def initialize(self) -> None:
        """Initialize whisper.cpp."""
        raise VoiceError(
            "whisper.cpp integration not yet implemented. Use WhisperSTT instead."
        )

    async def transcribe(self, audio_data: bytes) -> str:
        """Transcribe audio."""
        raise VoiceError("Not implemented")

    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """Transcribe streaming audio."""
        raise VoiceError("Not implemented")

    async def cleanup(self) -> None:
        """Clean up."""
        pass
