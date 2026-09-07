"""Tests for voice components."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import sys

import pytest

from hyusk.voice.base import AudioConfig, VoiceError


class TestAudioConfig:
    """Test AudioConfig."""

    def test_default_config(self) -> None:
        """Test default audio configuration."""
        config = AudioConfig()
        assert config.sample_rate == 16000
        assert config.channels == 1
        assert config.language == "en"
        assert config.model_size == "base"
        assert config.voice == "default"
        assert config.speed == 1.0

    def test_custom_config(self) -> None:
        """Test custom audio configuration."""
        config = AudioConfig(
            sample_rate=22050,
            language="es",
            model_size="small",
            voice="female",
            speed=1.2,
        )
        assert config.sample_rate == 22050
        assert config.language == "es"
        assert config.model_size == "small"
        assert config.voice == "female"
        assert config.speed == 1.2


class TestSystemTTS:
    """Test System TTS."""

    @pytest.mark.asyncio
    async def test_initialize_macos(self) -> None:
        """Test system TTS initialization on macOS."""
        from hyusk.voice.tts import SystemTTS

        with patch("platform.system", return_value="Darwin"):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.wait = AsyncMock()
                mock_exec.return_value = mock_proc

                config = AudioConfig()
                tts = SystemTTS(config)

                await tts.initialize()

                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_speak_macos(self) -> None:
        """Test system TTS speech on macOS."""
        from hyusk.voice.tts import SystemTTS

        with patch("platform.system", return_value="Darwin"):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                # Mock initialization check
                mock_init_proc = AsyncMock()
                mock_init_proc.returncode = 0
                mock_init_proc.wait = AsyncMock()

                # Mock speak process
                mock_speak_proc = AsyncMock()
                mock_speak_proc.returncode = 0
                mock_speak_proc.wait = AsyncMock()

                mock_exec.side_effect = [mock_init_proc, mock_speak_proc]

                config = AudioConfig()
                tts = SystemTTS(config)
                await tts.initialize()

                audio_data = await tts.speak("Hello")

                # System TTS returns empty bytes
                assert audio_data == b""
                assert mock_speak_proc.wait.called

    @pytest.mark.asyncio
    async def test_initialize_unsupported_platform(self) -> None:
        """Test initialization on unsupported platform."""
        from hyusk.voice.tts import SystemTTS

        with patch("platform.system", return_value="Linux"):
            config = AudioConfig()
            tts = SystemTTS(config)

            with pytest.raises(VoiceError, match="not implemented"):
                await tts.initialize()


class TestVoiceError:
    """Test VoiceError exception."""

    def test_voice_error(self) -> None:
        """Test VoiceError creation."""
        error = VoiceError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)


class TestVoiceBase:
    """Test voice base classes."""

    def test_speech_to_text_interface(self) -> None:
        """Test STT interface."""
        from hyusk.voice.base import SpeechToText

        config = AudioConfig()

        # Can't instantiate abstract class
        with pytest.raises(TypeError):
            SpeechToText(config)  # type: ignore

    def test_text_to_speech_interface(self) -> None:
        """Test TTS interface."""
        from hyusk.voice.base import TextToSpeech

        config = AudioConfig()

        # Can't instantiate abstract class
        with pytest.raises(TypeError):
            TextToSpeech(config)  # type: ignore

    def test_wake_word_detector_interface(self) -> None:
        """Test wake word detector interface."""
        from hyusk.voice.base import WakeWordDetector

        config = AudioConfig()

        # Can't instantiate abstract class
        with pytest.raises(TypeError):
            WakeWordDetector(config)  # type: ignore
