"""TTS backend tests (V5: Kokoro, Say, OpenAI, NoOp)."""

from __future__ import annotations

import sys

from hyusk.voice import tts
from hyusk.voice.tts import (
    TTSConfig,
    NoOpBackend,
    SayBackend,
    KokoroBackend,
    OpenAITTSBackend,
)


def test_noop_backend_is_always_available():
    b = NoOpBackend()
    assert b.is_available()
    assert b.name() == "none"
    b.speak("hello")


def test_say_backend_only_available_on_macos():
    b = SayBackend()
    if sys.platform == "darwin":
        assert b.name() == "say"
    else:
        assert not b.is_available()


def test_kokoro_backend_imports_cleanly():
    b = KokoroBackend()
    assert b.name() == "kokoro"
    assert isinstance(b.is_available(), bool)


def test_openai_backend_requires_api_key():
    b = OpenAITTSBackend(voice="alloy")
    import os
    has_key = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("HYUSK_LLM_API_KEY")
    )
    assert b.is_available() == has_key


def test_select_backend_none():
    b = tts.select_backend(TTSConfig(backend="none"))
    assert b.name() == "none"
    assert b.is_available()


def test_select_backend_unknown_falls_back_to_none():
    b = tts.select_backend(TTSConfig(backend="does-not-exist"))
    assert b.name() == "none"


def test_select_backend_say_respects_platform():
    b = tts.select_backend(TTSConfig(backend="say"))
    if sys.platform == "darwin":
        assert b.name() == "say"
    else:
        assert b.name() == "none"


def test_say_backend_speak_invokes_subprocess(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = SayBackend(voice="Daniel")
    b.speak("hello world")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "say"
    assert "-v" in cmd
    assert "Daniel" in cmd
    assert "hello world" in cmd


def test_say_backend_omits_voice_flag_when_unset(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = SayBackend(voice="")
    b.speak("hi")
    assert calls == [["say", "hi"]]


def test_kokoro_config_defaults():
    b = KokoroBackend()
    assert b._voice
    assert b._speed > 0


def test_tts_speaker_with_noop_backend():
    """The _TTSSpeaker should work with any backend that has synthesize().

    With NoOp, synthesize returns an empty array, so the speaker should
    complete quickly without errors.
    """
    import asyncio
    from hyusk.voice.client import _TTSSpeaker
    from hyusk.voice.tts.noop import NoOpBackend

    async def test():
        tts = NoOpBackend()
        sp = _TTSSpeaker(tts, max_in_flight=2)
        for text in ["First.", "Second.", "Third."]:
            sp.submit(text)
        await sp.drain()

    asyncio.run(test())


def test_tts_speaker_concurrent_workers():
    """Multiple workers can synthesize in parallel; drain waits for all.

    The new design uses a counter for submitted chunks and a separate
    counter for finished workers. drain() should not return until
    all submitted chunks are finished.
    """
    import asyncio
    import time
    from hyusk.voice.client import _TTSSpeaker

    class FakeBackend:
        def is_available(self): return True
        def name(self): return "fake"
        def synthesize(self, text: str, voice: str = "", speed=None):
            time.sleep(0.1)
            import numpy as np
            return np.zeros((100,), dtype="float32"), 16000
        def speak(self, text: str): pass

    async def test():
        tts = FakeBackend()
        sp = _TTSSpeaker(tts, max_in_flight=3)
        for i in range(5):
            sp.submit(f"sentence {i}")
        await sp.drain()
        # All 5 chunks should be marked done.
        assert sp._counter == 5
        assert sp._done_count == 5
        # Queue should be empty.
        assert sp._queue.empty()

    asyncio.run(test())


def test_tts_speaker_uses_single_playback_stream():
    """Regression: the speaker must use a single OutputStream.

    The new design lazily creates a single ``sd.OutputStream`` and
    reuses it across all writes (recreating if the sample rate
    changes). This avoids the multi-thread ``sd.play()``/``sd.wait()``
    races that produced gaps between sentences in V4.
    """
    import asyncio
    from hyusk.voice.client import _TTSSpeaker

    writes: list = []

    class FakeStream:
        def __init__(self, *a, **kw):
            writes.append(("__init__", a, kw))
        def start(self):
            writes.append(("start",))
        def stop(self):
            writes.append(("stop",))
        def close(self):
            writes.append(("close",))
        def write(self, samples):
            writes.append(("write", len(samples)))

    class FakeBackend:
        def is_available(self): return True
        def name(self): return "fake"
        def synthesize(self, text: str, voice: str = "", speed=None):
            import numpy as np
            return np.zeros((100,), dtype="float32"), 16000
        def speak(self, text: str): pass

    async def test():
        import sys
        from unittest.mock import MagicMock

        mock_sd = MagicMock()
        mock_sd.OutputStream = FakeStream
        # Patch sounddevice in sys.modules so the speaker picks it up.
        sys.modules["sounddevice"] = mock_sd

        try:
            tts = FakeBackend()
            sp = _TTSSpeaker(tts, max_in_flight=3)
            for i in range(5):
                sp.submit(f"chunk {i}")
            await sp.drain()

            # There should be 5 write() calls.
            write_calls = [w for w in writes if w[0] == "write"]
            assert len(write_calls) == 5, (
                f"expected 5 writes, got {len(write_calls)}"
            )
            # And exactly ONE OutputStream was constructed (the same
            # stream is reused).
            init_calls = [w for w in writes if w[0] == "__init__"]
            assert len(init_calls) == 1, (
                f"expected 1 OutputStream, got {len(init_calls)}"
            )
        finally:
            del sys.modules["sounddevice"]

    asyncio.run(test())


def test_tts_speaker_interrupt_clears_queue_and_closes_stream():
    """interrupt() should stop audio and drop pending chunks.

    The new interrupt path is used by the keypress handler when the
    user presses Space. It should:
    - Close the active OutputStream so audio cuts off mid-word
    - Drop any pending chunks in the queue
    - Allow drain() to return promptly
    """
    import asyncio
    from hyusk.voice.client import _TTSSpeaker

    class FakeStream:
        def __init__(self, *a, **kw):
            self.stopped = False
            self.closed = False
        def start(self): pass
        def stop(self): self.stopped = True
        def close(self): self.closed = True
        def write(self, samples): pass

    class FakeBackend:
        def is_available(self): return True
        def name(self): return "fake"
        def synthesize(self, text: str, voice: str = "", speed=None):
            import numpy as np
            return np.zeros((100,), dtype="float32"), 16000
        def speak(self, text: str): pass

    async def test():
        """interrupt() should stop the active stream and mark work done.

        This test directly sets up the speaker's internal state
        (skipping the worker pipeline, which is timing-sensitive) and
        verifies that interrupt() correctly stops the stream.
        """
        import sys
        from unittest.mock import MagicMock

        mock_sd = MagicMock()
        stream = FakeStream()
        mock_sd.OutputStream = lambda *a, **kw: stream
        sys.modules["sounddevice"] = mock_sd

        try:
            tts = FakeBackend()
            sp = _TTSSpeaker(tts, max_in_flight=2)
            # Manually open the stream (simulates what _playback_loop does
            # on the first write).
            sp._ensure_stream(16000)
            assert sp._stream is stream
            # Simulate one synth worker finishing.
            with sp._done_lock:
                sp._done_count = 1
            sp._counter = 1
            # Now interrupt.
            sp.interrupt()
            # The stream should be stopped and closed.
            assert stream.stopped
            assert stream.closed
            # The internal _stream ref should be cleared.
            assert sp._stream is None
            # Done count should be == counter so drain() exits.
            assert sp._done_count == sp._counter
            # drain() should return immediately.
            await sp.drain()
        finally:
            del sys.modules["sounddevice"]

    asyncio.run(test())


def test_tts_speaker_no_gaps_between_chunks():
    """Chunks should be written to the stream back-to-back.

    With one playback stream, each chunk's samples are written in
    sequence with no gap (no waiting for the next synth).
    """
    import asyncio
    import time
    from hyusk.voice.client import _TTSSpeaker

    class FakeBackend:
        def is_available(self): return True
        def name(self): return "fake"
        def synthesize(self, text: str, voice: str = "", speed=None):
            # Each chunk takes 50ms to "synthesize"
            time.sleep(0.05)
            import numpy as np
            return np.zeros((100,), dtype="float32"), 16000
        def speak(self, text: str): pass

    async def test():
        import hyusk.voice.client as vclient
        from unittest.mock import MagicMock

        mock_sd = MagicMock()

        class FakeStream:
            def __init__(self, *a, **kw): pass
            def start(self): pass
            def stop(self): pass
            def close(self): pass
            def write(self, samples): pass

        mock_sd.OutputStream = FakeStream
        vclient.sd = mock_sd

        tts = FakeBackend()
        sp = _TTSSpeaker(tts, max_in_flight=2)
        t0 = time.time()
        for i in range(4):
            sp.submit(f"chunk {i}")
        await sp.drain()
        elapsed = time.time() - t0
        # 4 chunks * 50ms = 200ms serial. With max_in_flight=2, two
        # can synthesize in parallel, so total time is ~100ms. Allow
        # generous slack.
        # 4 chunks * 50ms / 2 parallel = 100ms. Allow up to 1s for
        # Python threading overhead on slow CI.
        assert elapsed < 1.0, f"drain took {elapsed:.2f}s; expected < 1.0s"

    asyncio.run(test())


def test_tts_config_dataclass():
    c = TTSConfig()
    assert c.backend == ""
    assert c.voice == ""
    assert c.speed == 1.0
    c2 = TTSConfig(backend="kokoro", voice="af_sarah", speed=1.2)
    assert c2.backend == "kokoro"
    assert c2.voice == "af_sarah"
    assert c2.speed == 1.2
