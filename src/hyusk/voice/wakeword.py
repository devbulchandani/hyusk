"""Wake word detection implementation."""

import asyncio
import logging
from typing import Optional

try:
    import pvporcupine
    
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False

from hyusk.voice.base import WakeWordDetector, AudioConfig, VoiceError
from hyusk.voice.audio import AudioInput

logger = logging.getLogger(__name__)


class PorcupineWakeWord(WakeWordDetector):
    """
    Wake word detection using Picovoice Porcupine.

    Requires a Porcupine access key from https://console.picovoice.ai/
    """

    def __init__(self, config: AudioConfig, access_key: Optional[str] = None):
        super().__init__(config)
        self._access_key = access_key
        self._porcupine: Optional[pvporcupine.Porcupine] = None
        self._audio_input: Optional[AudioInput] = None
        self._detection_task: Optional[asyncio.Task] = None
        self._wake_detected = False

    async def initialize(self) -> None:
        """Initialize Porcupine."""
        if not PORCUPINE_AVAILABLE:
            raise VoiceError(
                "Porcupine not available. Install with: pip install pvporcupine"
            )

        if not self._access_key:
            raise VoiceError(
                "Porcupine access key required. Get one at https://console.picovoice.ai/"
            )

        logger.info("Initializing Porcupine wake word detector")

        try:
            # Create Porcupine instance
            # Using built-in "computer" wake word as fallback
            self._porcupine = pvporcupine.create(
                access_key=self._access_key,
                keywords=["computer"],  # Built-in keyword
                sensitivities=[self.config.sensitivity],
            )

            # Initialize audio input
            self._audio_input = AudioInput(self.config)
            await self._audio_input.initialize()

            logger.info("Porcupine initialized successfully")
        except Exception as e:
            raise VoiceError(f"Failed to initialize Porcupine: {e}")

    async def wait_for_wake_word(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for wake word detection.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            True if detected, False if timeout
        """
        if not self._porcupine or not self._audio_input:
            raise VoiceError("Wake word detector not initialized")

        self._wake_detected = False

        try:
            await self._audio_input.start_recording()

            start_time = asyncio.get_event_loop().time()

            while not self._wake_detected:
                # Check timeout
                if timeout:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= timeout:
                        logger.debug("Wake word detection timeout")
                        return False

                # Read audio chunk
                pcm = await self._audio_input.read_chunk()

                # Process with Porcupine
                loop = asyncio.get_event_loop()
                keyword_index = await loop.run_in_executor(
                    None, self._porcupine.process, pcm
                )

                if keyword_index >= 0:
                    logger.info("Wake word detected!")
                    self._wake_detected = True
                    return True

                # Small delay to prevent busy loop
                await asyncio.sleep(0.01)

            return True

        except Exception as e:
            raise VoiceError(f"Wake word detection failed: {e}")
        finally:
            await self._audio_input.stop_recording()

    async def start_listening(self) -> None:
        """Start listening for wake word in background."""
        if self._is_listening:
            logger.warning("Already listening for wake word")
            return

        if not self._porcupine or not self._audio_input:
            raise VoiceError("Wake word detector not initialized")

        self._is_listening = True
        self._detection_task = asyncio.create_task(self._listen_loop())
        logger.info("Started wake word listening")

    async def stop_listening(self) -> None:
        """Stop listening for wake word."""
        if not self._is_listening:
            return

        self._is_listening = False

        if self._detection_task:
            self._detection_task.cancel()
            try:
                await self._detection_task
            except asyncio.CancelledError:
                pass
            self._detection_task = None

        logger.info("Stopped wake word listening")

    async def _listen_loop(self) -> None:
        """Background listening loop."""
        try:
            while self._is_listening:
                detected = await self.wait_for_wake_word(timeout=1.0)
                if detected:
                    logger.info("Wake word detected in background")
                    # Could emit event here for orchestrator
                    self._wake_detected = False

        except asyncio.CancelledError:
            logger.debug("Wake word listening cancelled")
        except Exception as e:
            logger.error(f"Wake word listening error: {e}")

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop_listening()

        if self._audio_input:
            await self._audio_input.cleanup()
            self._audio_input = None

        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None

        logger.info("Porcupine cleaned up")


class SimpleWakeWord(WakeWordDetector):
    """
    Simple wake word detector using STT.

    This is a fallback implementation that uses speech-to-text
    to detect the wake phrase. Not recommended for always-on use
    due to high resource consumption.
    """

    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self._audio_input: Optional[AudioInput] = None
        self._stt: Optional[object] = None  # Will import STT

    async def initialize(self) -> None:
        """Initialize simple wake word detector."""
        from hyusk.voice.stt import WhisperSTT

        self._audio_input = AudioInput(self.config)
        await self._audio_input.initialize()

        self._stt = WhisperSTT(self.config)
        await self._stt.initialize()

        logger.info("Simple wake word detector initialized")
        logger.warning(
            "Using STT for wake word detection. This is resource-intensive. "
            "Consider using PorcupineWakeWord with an access key."
        )

    async def wait_for_wake_word(self, timeout: Optional[float] = None) -> bool:
        """Wait for wake phrase using STT."""
        if not self._audio_input or not self._stt:
            raise VoiceError("Wake word detector not initialized")

        try:
            # Record for 2 seconds at a time
            audio = await self._audio_input.record(2.0)

            # Transcribe
            text = await self._stt.transcribe(audio)
            text_lower = text.lower().strip()

            # Check for wake phrase
            wake_phrase = self.config.wake_phrase.lower()
            if wake_phrase in text_lower or text_lower in wake_phrase:
                logger.info(f"Wake phrase detected: {text}")
                return True

            return False

        except Exception as e:
            raise VoiceError(f"Simple wake word detection failed: {e}")

    async def start_listening(self) -> None:
        """Start listening - not recommended for simple implementation."""
        logger.warning("Continuous listening not recommended for SimpleWakeWord")
        self._is_listening = True

    async def stop_listening(self) -> None:
        """Stop listening."""
        self._is_listening = False

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._audio_input:
            await self._audio_input.cleanup()
        if self._stt:
            await self._stt.cleanup()
        logger.info("Simple wake word cleaned up")
