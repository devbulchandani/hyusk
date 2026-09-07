"""Text-to-speech implementation using Kokoro TTS."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, AsyncIterator

try:
    import pyttsx3
    
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

from hyusk.voice.base import TextToSpeech, AudioConfig, VoiceError

logger = logging.getLogger(__name__)


class KokoroTTS(TextToSpeech):
    """
    Text-to-speech using Kokoro TTS.

    This is a placeholder implementation using pyttsx3 as a fallback.
    Future implementation will use actual Kokoro TTS models.
    """

    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self._engine: Optional[pyttsx3.Engine] = None

    async def initialize(self) -> None:
        """Initialize TTS engine."""
        if not PYTTSX3_AVAILABLE:
            raise VoiceError(
                "pyttsx3 not available. Install with: pip install pyttsx3"
            )

        logger.info("Initializing Kokoro TTS (pyttsx3 fallback)")

        try:
            # Initialize in executor
            loop = asyncio.get_event_loop()
            self._engine = await loop.run_in_executor(None, pyttsx3.init)

            # Configure voice properties
            self._engine.setProperty("rate", int(150 * self.config.speed))
            self._engine.setProperty("volume", 1.0)

            # Try to set voice if specified
            if self.config.voice != "default":
                voices = self._engine.getProperty("voices")
                for voice in voices:
                    if self.config.voice.lower() in voice.name.lower():
                        self._engine.setProperty("voice", voice.id)
                        break

            logger.info("TTS engine initialized")
        except Exception as e:
            raise VoiceError(f"Failed to initialize TTS: {e}")

    async def speak(self, text: str) -> bytes:
        """
        Convert text to speech.

        Args:
            text: Text to speak

        Returns:
            Audio data as bytes

        Raises:
            VoiceError: If synthesis fails
        """
        if not self._engine:
            raise VoiceError("TTS engine not initialized")

        try:
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = Path(f.name)

            # Generate speech
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._engine.save_to_file, text, str(temp_path)
            )
            await loop.run_in_executor(None, self._engine.runAndWait)

            # Read audio data
            audio_data = temp_path.read_bytes()

            # Clean up
            temp_path.unlink()

            logger.info(f"Generated speech for: {text[:50]}...")
            return audio_data

        except Exception as e:
            raise VoiceError(f"Speech synthesis failed: {e}")

    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream text-to-speech audio.

        Note: pyttsx3 doesn't support true streaming, so we generate
        the full audio and yield it in chunks.

        Args:
            text: Text to speak

        Yields:
            Audio chunks
        """
        if not self._engine:
            raise VoiceError("TTS engine not initialized")

        try:
            # Generate full audio
            audio_data = await self.speak(text)

            # Yield in chunks
            chunk_size = self.config.chunk_size * 2  # 16-bit samples
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i : i + chunk_size]

        except Exception as e:
            raise VoiceError(f"Stream synthesis failed: {e}")

    async def stop(self) -> None:
        """Stop current speech."""
        if not self._engine:
            return

        self._is_speaking = False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._engine.stop)
            logger.info("Speech stopped")
        except Exception as e:
            logger.warning(f"Failed to stop speech: {e}")

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._engine:
            try:
                await self.stop()
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._engine.stop)
            except Exception:
                pass
            self._engine = None
        logger.info("TTS cleaned up")


class SystemTTS(TextToSpeech):
    """
    Text-to-speech using system commands.

    Fallback implementation using macOS 'say' command or equivalent.
    """

    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self._process: Optional[asyncio.subprocess.Process] = None

    async def initialize(self) -> None:
        """Check if system TTS is available."""
        import platform

        system = platform.system()

        if system == "Darwin":  # macOS
            # Check if 'say' command exists
            try:
                proc = await asyncio.create_subprocess_exec(
                    "which", "say", stdout=asyncio.subprocess.PIPE
                )
                await proc.wait()
                if proc.returncode != 0:
                    raise VoiceError("macOS 'say' command not found")
            except Exception as e:
                raise VoiceError(f"System TTS not available: {e}")
        else:
            raise VoiceError(f"System TTS not implemented for {system}")

        logger.info("System TTS initialized")

    async def speak(self, text: str) -> bytes:
        """
        Convert text to speech using system command.

        Note: This implementation doesn't return audio data,
        it plays directly through system audio.

        Returns empty bytes for compatibility.
        """
        if self._is_speaking:
            await self.stop()

        try:
            self._is_speaking = True

            # Use macOS 'say' command with custom rate
            rate = int(175 * self.config.speed)
            self._process = await asyncio.create_subprocess_exec(
                "say",
                "-r",
                str(rate),
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await self._process.wait()
            self._is_speaking = False

            logger.info(f"Spoke: {text[:50]}...")
            return b""  # System TTS plays directly

        except Exception as e:
            self._is_speaking = False
            raise VoiceError(f"System TTS failed: {e}")

    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream is not supported for system TTS."""
        await self.speak(text)
        yield b""

    async def stop(self) -> None:
        """Stop current speech."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        self._is_speaking = False
        self._process = None
        logger.info("System speech stopped")

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop()
        logger.info("System TTS cleaned up")
