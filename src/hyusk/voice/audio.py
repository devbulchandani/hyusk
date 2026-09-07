"""Audio input/output utilities."""

import asyncio
import logging
import wave
from pathlib import Path
from typing import Optional, AsyncIterator

try:
    import pyaudio
    
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

from hyusk.voice.base import AudioConfig, VoiceError

logger = logging.getLogger(__name__)


class AudioInput:
    """Handle microphone input."""

    def __init__(self, config: AudioConfig):
        if not PYAUDIO_AVAILABLE:
            raise VoiceError(
                "PyAudio not available. Install with: pip install pyaudio"
            )

        self.config = config
        self._audio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._is_recording = False

    async def initialize(self) -> None:
        """Initialize PyAudio."""
        try:
            self._audio = pyaudio.PyAudio()
            logger.info("Audio input initialized")
        except Exception as e:
            raise VoiceError(f"Failed to initialize audio input: {e}")

    async def start_recording(self) -> None:
        """Start recording from microphone."""
        if self._is_recording:
            logger.warning("Already recording")
            return

        if not self._audio:
            await self.initialize()

        try:
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=self.config.chunk_size,
            )
            self._is_recording = True
            logger.info("Started recording")
        except Exception as e:
            raise VoiceError(f"Failed to start recording: {e}")

    async def stop_recording(self) -> None:
        """Stop recording."""
        if not self._is_recording:
            return

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

        self._is_recording = False
        logger.info("Stopped recording")

    async def read_chunk(self) -> bytes:
        """
        Read one chunk of audio data.

        Returns:
            Audio data bytes

        Raises:
            VoiceError: If not recording or read fails
        """
        if not self._is_recording or not self._stream:
            raise VoiceError("Not currently recording")

        try:
            # Run blocking read in executor
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, self._stream.read, self.config.chunk_size
            )
            return data
        except Exception as e:
            raise VoiceError(f"Failed to read audio: {e}")

    async def record_stream(
        self, duration: Optional[float] = None
    ) -> AsyncIterator[bytes]:
        """
        Stream audio chunks.

        Args:
            duration: Optional duration in seconds

        Yields:
            Audio chunks
        """
        await self.start_recording()

        try:
            start_time = asyncio.get_event_loop().time()
            while True:
                if duration:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= duration:
                        break

                chunk = await self.read_chunk()
                yield chunk

        finally:
            await self.stop_recording()

    async def record(self, duration: float) -> bytes:
        """
        Record audio for a specific duration.

        Args:
            duration: Duration in seconds

        Returns:
            Complete audio data
        """
        chunks = []
        async for chunk in self.record_stream(duration):
            chunks.append(chunk)
        return b"".join(chunks)

    async def save_recording(self, audio_data: bytes, filepath: Path) -> None:
        """
        Save audio data to WAV file.

        Args:
            audio_data: Raw audio bytes
            filepath: Output file path
        """
        try:
            with wave.open(str(filepath), "wb") as wf:
                wf.setnchannels(self.config.channels)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(audio_data)
            logger.info(f"Saved recording to {filepath}")
        except Exception as e:
            raise VoiceError(f"Failed to save recording: {e}")

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop_recording()
        if self._audio:
            self._audio.terminate()
            self._audio = None
        logger.info("Audio input cleaned up")

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording


class AudioOutput:
    """Handle audio playback."""

    def __init__(self, config: AudioConfig):
        if not PYAUDIO_AVAILABLE:
            raise VoiceError(
                "PyAudio not available. Install with: pip install pyaudio"
            )

        self.config = config
        self._audio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._is_playing = False
        self._stop_requested = False

    async def initialize(self) -> None:
        """Initialize PyAudio."""
        try:
            self._audio = pyaudio.PyAudio()
            logger.info("Audio output initialized")
        except Exception as e:
            raise VoiceError(f"Failed to initialize audio output: {e}")

    async def play(self, audio_data: bytes) -> None:
        """
        Play audio data.

        Args:
            audio_data: Raw audio bytes to play

        Raises:
            VoiceError: If playback fails
        """
        if self._is_playing:
            await self.stop()

        if not self._audio:
            await self.initialize()

        try:
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                output=True,
            )

            self._is_playing = True
            self._stop_requested = False

            # Play in chunks to allow interruption
            chunk_size = self.config.chunk_size * 2  # 16-bit samples
            loop = asyncio.get_event_loop()

            for i in range(0, len(audio_data), chunk_size):
                if self._stop_requested:
                    logger.info("Playback interrupted")
                    break

                chunk = audio_data[i : i + chunk_size]
                await loop.run_in_executor(None, self._stream.write, chunk)

        except Exception as e:
            raise VoiceError(f"Failed to play audio: {e}")
        finally:
            await self._cleanup_stream()

    async def play_stream(self, audio_stream: AsyncIterator[bytes]) -> None:
        """
        Play streaming audio.

        Args:
            audio_stream: Async iterator of audio chunks

        Raises:
            VoiceError: If playback fails
        """
        if self._is_playing:
            await self.stop()

        if not self._audio:
            await self.initialize()

        try:
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                output=True,
            )

            self._is_playing = True
            self._stop_requested = False

            loop = asyncio.get_event_loop()

            async for chunk in audio_stream:
                if self._stop_requested:
                    logger.info("Playback interrupted")
                    break

                await loop.run_in_executor(None, self._stream.write, chunk)

        except Exception as e:
            raise VoiceError(f"Failed to play audio stream: {e}")
        finally:
            await self._cleanup_stream()

    async def stop(self) -> None:
        """Stop current playback."""
        if not self._is_playing:
            return

        self._stop_requested = True
        logger.info("Stopping playback")

        # Give it a moment to finish current chunk
        await asyncio.sleep(0.1)

    async def _cleanup_stream(self) -> None:
        """Clean up playback stream."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        self._is_playing = False

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop()
        await self._cleanup_stream()
        if self._audio:
            self._audio.terminate()
            self._audio = None
        logger.info("Audio output cleaned up")

    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._is_playing
