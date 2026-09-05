"""Voice client (V4.1).

A standalone process that:
  1. Captures the user's voice (microphone) or reads typed text.
  2. Pushes the transcript to the Hyusk daemon over WebSocket.
  3. Receives the agent's reply and either prints it or speaks it via TTS.

Modes
-----

`--text`     Read lines from stdin. Default. Works in any environment.

`--mic`      Use the system microphone. Records audio to a temp file,
            transcribes via the configured STT backend, and submits the
            text to the daemon. Available only if an STT backend is
            installed.

The voice client uses the same WebSocket protocol as the regular CLI.
Each user turn becomes a `run` message; the agent's text deltas are
accumulated into a single reply, which is printed and (if TTS is
enabled) spoken aloud.

Configuration
-------------

  [voice]
  tts_backend = "say" | "kokoro" | "openai" | "none"  (default: say on macOS)
  tts_voice   = "<backend-specific voice name>"
  stt_backend = "mlx-whisper" | "openai-whisper" | "whisper-api" | "text"

Optional dependencies (install via `uv sync --extra voice`):

  sounddevice         microphone recording + audio playback
  kokoro-onnx         local neural TTS (recommended)
  mlx-whisper         local Whisper on Apple Silicon
  openai-whisper      cross-platform local Whisper
  openai              OpenAI TTS / Whisper API
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import threading
import time
from typing import Any

from ..client.client import DaemonClient, EventMessage, TaskDone
from ..config.config import Config
from . import stt, tts


def _read_text_loop() -> list[str]:
    """Read user inputs from stdin. Returns the list of inputs.

    Each non-empty line is treated as a separate turn. Ctrl-D / EOF
    ends the session.
    """
    print("voice (text mode): type a turn and press Enter. Ctrl-D to exit.", flush=True)
    while True:
        try:
            line = input("> ")
        except EOFError:
            return []
        line = line.strip()
        if not line:
            continue
        return [line]


def _rms(chunk) -> float:
    """Return the root-mean-square amplitude of an audio chunk."""
    import numpy as np
    return float(np.sqrt(np.mean(chunk * chunk)))


def _is_speech(chunk, threshold: float = 0.003) -> bool:
    """Return True if the audio chunk looks like speech.

    The default threshold (0.003) is conservative — quiet rooms with
    built-in laptop mics can produce RMS well below 0.01 during
    speech. Increase this if the mic picks up too much background;
    decrease it if speech isn't being detected.
    """
    return _rms(chunk) > threshold


def _level_bar(rms: float, width: int = 20) -> str:
    """Return a small ASCII level meter showing how loud `rms` is."""
    # Map 0..0.1 to 0..width (speech typically peaks around 0.05-0.1).
    fill = min(width, int(rms * width * 10))
    return "[" + "█" * fill + "·" * (width - fill) + "]"


async def _record_and_transcribe(
    stt_backend,
    *,
    max_duration: float = 6.0,
    silence_timeout: float = 1.0,
    abort_event: "threading.Event | None" = None,
) -> str:
    """Record from the microphone until the user stops talking, then transcribe.

    Uses a simple energy-based VAD:
      - start recording when input is detected
      - stop after `silence_timeout` seconds of below-threshold audio
      - hard-cap at `max_duration` seconds

    A live level meter is drawn to stderr so the user can see that the
    mic is picking up audio.
    """
    try:
        import sounddevice as sd
    except ImportError:
        print(
            "[voice] mic mode needs `sounddevice`: `uv pip install sounddevice`",
            file=sys.stderr,
        )
        return input("> ").strip()
    try:
        import numpy as np
    except ImportError:
        print("[voice] mic mode needs numpy: `uv pip install numpy`", file=sys.stderr)
        return input("> ").strip()
    try:
        import scipy.io.wavfile as wav
    except ImportError:
        print("[voice] mic mode needs scipy: `uv pip install scipy`", file=sys.stderr)
        return input("> ").strip()

    sample_rate = 16000
    chunk_duration = 0.05  # 50 ms per chunk
    chunk_samples = int(sample_rate * chunk_duration)

    # Auto-calibrate the noise floor: take a few chunks of "silence" and
    # set the speech threshold to several times the noise RMS. This
    # adapts to quiet rooms and noisy environments automatically.
    sys.stderr.write("[voice] calibrating noise floor... ")
    sys.stderr.flush()

    def _aborted() -> bool:
        return abort_event is not None and abort_event.is_set()

    noise_chunks: list = []
    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32") as stream:
            for _ in range(20):  # ~1 second of "silence"
                if _aborted():
                    return ""
                chunk, _ = stream.read(chunk_samples)
                noise_chunks.append(chunk.copy())
    except Exception as exc:
        print(f"[voice] cannot open mic: {exc}. Falling back to text.", file=sys.stderr)
        return input("> ").strip()
    noise_rms = max((_rms(c) for c in noise_chunks), default=0.001)
    threshold = max(0.003, noise_rms * 4.0)
    sys.stderr.write(
        f"noise_rms={noise_rms:.4f}, threshold={threshold:.4f}\n"
    )
    sys.stderr.flush()

    if noise_rms > 0.3:
        print(
            f"[voice] WARNING: noise floor is high ({noise_rms:.3f}). "
            "Try a quieter room or check mic levels.",
            file=sys.stderr,
        )

    # Now listen for actual speech.
    sys.stderr.write(
        f"[voice] listening (max {max_duration:.0f}s, threshold={threshold:.4f}). "
        "Speak; auto-stops when you pause.\n"
    )
    sys.stderr.flush()

    is_speaking = False
    silence_chunks = 0
    elapsed = 0.0
    audio_chunks: list = []
    last_bar = ""

    def _show_meter(rms: float, is_speech: bool) -> None:
        nonlocal last_bar
        bar = _level_bar(rms)
        marker = "▌ speaking" if is_speech else "  ...    "
        line = f"\r    {bar} {marker}"
        # Pad to overwrite the previous line.
        line = line.ljust(len(last_bar) + 10)
        last_bar = line
        sys.stderr.write(line)
        sys.stderr.flush()

    # If an abort_event is set (e.g. user pressed Space to interrupt
    # a previous turn), discard the calibration audio and the recording.
    def _aborted() -> bool:
        return abort_event is not None and abort_event.is_set()

    if _aborted():
        return ""

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32") as stream:
            while elapsed < max_duration:
                # Check for abort periodically (every 50ms).
                if _aborted():
                    return ""
                chunk, _ = stream.read(chunk_samples)
                rms = _rms(chunk)
                audio_chunks.append(chunk.copy())
                elapsed += chunk_duration

                if rms > threshold:
                    is_speaking = True
                    silence_chunks = 0
                    _show_meter(rms, is_speech=True)
                else:
                    if is_speaking:
                        silence_chunks += 1
                        silence_secs = silence_chunks * chunk_duration
                        _show_meter(rms, is_speech=False)
                        if silence_secs >= silence_timeout:
                            break
                    else:
                        # Pre-speech silence — show the meter occasionally
                        # so the user can see the mic is alive.
                        if int(elapsed * 5) % 5 == 0:
                            _show_meter(rms, is_speech=False)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"\n[voice] recording failed: {exc}", file=sys.stderr)
        return ""

    # Clear the meter line.
    sys.stderr.write("\n")
    sys.stderr.flush()

    if not is_speaking or not audio_chunks:
        print("[voice] (no speech detected — try speaking louder or check the mic)", file=sys.stderr)
        return ""

    audio = np.concatenate(audio_chunks, axis=0)
    # Trim trailing silence (last `silence_chunks` chunks).
    if silence_chunks > 0:
        keep = max(1, len(audio_chunks) - silence_chunks)
        audio = np.concatenate(audio_chunks[:keep], axis=0)

    duration = len(audio) / sample_rate
    if duration < 0.3:
        print(f"[voice] (captured only {duration:.2f}s; too short, ignoring)", file=sys.stderr)
        return ""

    print(f"[voice] captured {duration:.1f}s of audio; transcribing...", file=sys.stderr)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav.write(f.name, sample_rate, (audio * 32767).astype("int16"))
        path = f.name
    try:
        text = stt_backend.transcribe(path)
    except Exception as exc:
        print(f"[voice] transcription failed: {exc}", file=sys.stderr)
        text = ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return (text or "").strip()


async def _run_text_mode(
    client: DaemonClient, model: str | None, tts_backend
) -> int:
    print("connected; ready for input.", flush=True)
    while True:
        try:
            line = input("> ")
        except EOFError:
            return 0
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit", ":q"):
            return 0
        await _run_turn(client, line, model, tts_backend)
    return 0


def _load_stt_backend_name() -> str:
    """Read voice.stt_backend from the user config file. Empty string
    means "use the platform default"."""
    import tomllib
    from pathlib import Path

    try:
        cfg_path = Path.home() / "Library" / "Application Support" / "hyusk" / "config.toml"
        if cfg_path.exists():
            with cfg_path.open("rb") as f:
                return tomllib.load(f).get("voice", {}).get("stt_backend", "") or ""
    except Exception:
        pass
    return ""


async def _run_mic_mode(
    client: DaemonClient, model: str | None, tts_backend
) -> int:
    """Mic mode: record, transcribe, submit.

    Resolution order for the STT backend:
      1. `voice.stt_backend` in the user config (e.g. `mlx-whisper`).
      2. Platform default (mlx-whisper on macOS, whisper-api elsewhere).
      3. Fall back to stdin if the configured backend is unavailable.
    """
    stt_name = _load_stt_backend_name()
    backend = stt.select_backend(stt_name)

    # If the user asked for a real STT backend but it isn't available,
    # explain the situation. If they got the text backend, just use it.
    if backend.name() == "text" and stt_name not in ("", "text"):
        print(
            f"[voice] STT backend {stt_name!r} not installed; falling back to text mode.",
            file=sys.stderr,
        )
        print(
            "        hint: install with `uv pip install mlx-whisper` (macOS) "
            "or `uv pip install openai-whisper`",
            file=sys.stderr,
        )
        return await _run_text_mode(client, model, tts_backend)
    if not backend.is_available():
        print(
            f"[voice] STT backend {backend.name()} not available; falling back to text mode.",
            file=sys.stderr,
        )
        return await _run_text_mode(client, model, tts_backend)

    # Verify the mic itself is reachable.
    try:
        import sounddevice as sd

        try:
            sd.query_devices(kind="input")
        except Exception as exc:
            print(
                f"[voice] cannot access input device: {exc}. Falling back to text mode.",
                file=sys.stderr,
            )
            return await _run_text_mode(client, model, tts_backend)
    except ImportError:
        print(
            "[voice] mic mode needs `sounddevice`: `uv pip install sounddevice`",
            file=sys.stderr,
        )
        return await _run_text_mode(client, model, tts_backend)

    print(
        f"connected (mic mode, STT={backend.name()}); speak; auto-stops when you pause. "
        "Ctrl-D to exit.",
        flush=True,
    )
    # Keep a flag so the keypress handler can short-circuit the recorder.
    # When the user presses Space, we cancel the current daemon task,
    # stop TTS playback, and discard the in-flight audio (so the key click
    # doesn't get sent to the agent as a fake transcript).
    record_abort = threading.Event()

    # When the keypress handler fires, mark the recorder's abort flag.
    # We monkey-patch the on_interrupt callback below (in the main
    # function) to do this in addition to the existing TTS / daemon
    # cancel logic.

    try:
        while True:
            record_abort.clear()
            text = await _record_and_transcribe(
                backend, abort_event=record_abort
            )
            # Reset the keypress-cancelled flag for the next turn.
            cancel_event.clear()
            if not text:
                continue
            if text.strip().lower() in ("exit", "quit"):
                return 0
            print(f"[voice] heard: {text!r}", file=sys.stderr)
            await _run_turn(
                client, text, model, tts_backend, record_abort=record_abort
            )
            # Brief "ready" hint so the user knows the mic is listening again
            sys.stderr.write("[listening]\n")
            sys.stderr.flush()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Any error in one turn should not kill the voice client. Log
        # the error and continue listening.
        print(f"[voice] turn error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    finally:
        if kp_handle_holder:
            try:
                kp_handle_holder[0].stop()
            except Exception:
                pass
    return 0


async def _await_done(done_future: asyncio.Future) -> None:
    """Await the done future, ignoring its return value (just signaling)."""
    await done_future


async def _await_press(handle) -> None:
    """Block until the keypress handle reports a press."""
    loop = asyncio.get_event_loop()
    while not handle.was_pressed():
        await asyncio.sleep(0.05)


class _TTSSpeaker:
    """Play TTS audio with strict ordering, no gaps.

    Design: a SINGLE playback thread consumes chunks from a queue
    in order and writes them to one persistent
    ``sounddevice.OutputStream``. Multiple synth workers run in
    parallel and push into the queue, so synthesis overlaps with
    playback. Because there is exactly one playback thread writing
    to one stream, there are no gaps between sentences (a common
    bug with multi-thread ``sd.play()``/``sd.wait()``).

    Usage::

        speaker = _TTSSpeaker(tts_backend, max_in_flight=2)
        speaker.submit("First sentence.")
        speaker.submit("Second sentence.")
        await speaker.drain()  # wait for both to finish
    """

    def __init__(self, tts_backend, max_in_flight: int = 2) -> None:
        import queue as _q

        self._backend = tts_backend
        self._max = max(1, max_in_flight)
        self._lock = threading.Lock()
        # Total chunks submitted (used as a sequence id, and for drain).
        self._counter = 0
        # Number of synth workers that have finished (success or fail).
        self._done_count = 0
        self._done_lock = threading.Lock()
        # FIFO queue of (seq, samples, sample_rate) from synth workers.
        # Sentinel ``None`` means a worker finished (for capacity tracking).
        self._queue: "queue.Queue" = _q.Queue()
        # OutputStream (single, lazily created).
        self._stream = None
        self._stream_sample_rate = None
        self._stream_lock = threading.Lock()
        # Whether the playback thread has been started.
        self._started = False

    def submit(self, text: str) -> None:
        """Queue a chunk for synthesis + playback. Returns immediately."""
        if not text.strip():
            return
        with self._lock:
            seq = self._counter
            self._counter += 1
        # Bound concurrency: don't start more than max_in_flight workers.
        self._wait_for_capacity()
        threading.Thread(
            target=self._worker, args=(seq, text), daemon=True
        ).start()

    def _wait_for_capacity(self) -> None:
        while True:
            with self._done_lock:
                in_flight = self._counter - self._done_count
            if in_flight < self._max:
                return
            time.sleep(0.001)

    def _ensure_stream(self, sample_rate: int) -> None:
        """Open a single persistent OutputStream at the given sample rate."""
        with self._stream_lock:
            if self._stream is not None and sample_rate != self._stream_sample_rate:
                # Sample rate changed; close and reopen.
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._stream is None:
                import sounddevice as sd
                self._stream = sd.OutputStream(
                    samplerate=sample_rate, channels=1, dtype="float32"
                )
                self._stream.start()
                self._stream_sample_rate = sample_rate

    def _worker(self, seq: int, text: str) -> None:
        try:
            samples, sr = self._backend.synthesize(text)
        except Exception as exc:
            logger = __import__("logging").getLogger("hyusk.voice.tts")
            logger.warning("synthesis failed for chunk %d: %s", seq, exc)
            with self._done_lock:
                self._done_count += 1
            self._queue.put(None)
            return
        self._queue.put((seq, samples, sr))
        with self._done_lock:
            self._done_count += 1

    def _playback_loop(self) -> None:
        """Drain the queue in order; write each chunk to the output stream."""
        expected_seq = 0
        pending: dict = {}
        while True:
            # If next seq is already in pending, play it.
            if expected_seq in pending:
                samples, sr = pending.pop(expected_seq)
                self._ensure_stream(sr)
                with self._stream_lock:
                    self._stream.write(samples)
                expected_seq += 1
                continue
            # Otherwise wait for the next chunk from the queue.
            try:
                item = self._queue.get(timeout=0.05)
            except Exception:
                continue
            if item is None:
                # Worker finished; loop again to drain any pending
                # items that just arrived.
                continue
            seq, samples, sr = item
            if seq == expected_seq:
                self._ensure_stream(sr)
                with self._stream_lock:
                    self._stream.write(samples)
                expected_seq += 1
            else:
                # Out of order; stash and wait.
                pending[seq] = (samples, sr)


    def interrupt(self) -> None:
        """Cut off any in-flight audio and discard pending chunks.

        Called by the keypress handler when the user presses Space.
        Closes the OutputStream (so audio cuts off mid-word) and
        drops any queued chunks. Safe to call multiple times.
        """
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
                self._stream_sample_rate = None
        # Drop pending chunks from the queue.
        while True:
            try:
                self._queue.get_nowait()
            except Exception:
                break
        # Mark all in-flight as done so drain() returns.
        with self._done_lock:
            self._done_count = self._counter
        # Wake up the playback thread so it sees the closed stream.
        self._queue.put(None)

    async def drain(self) -> None:
        """Wait until all queued chunks have been written to the stream."""
        # Start the playback thread once.
        if not self._started:
            self._started = True
            threading.Thread(
                target=self._playback_loop, daemon=True
            ).start()
        # Wait for all synth workers to finish.
        deadline = time.time() + 60.0
        while time.time() < deadline:
            with self._lock:
                total = self._counter
            with self._done_lock:
                done = self._done_count
            if done >= total:
                break
            await asyncio.sleep(0.01)
        # Give the playback thread time to drain pending chunks.
        # We poll the queue size until it's empty (with a small grace
        # period for the last write() to complete).
        deadline = time.time() + 5.0
        while time.time() < deadline and not self._queue.empty():
            await asyncio.sleep(0.02)
        # Close the stream so subsequent sd.play() calls don't conflict.
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
async def _run_turn(
    client: DaemonClient, text: str, model: str | None, tts_backend,
    record_abort: "threading.Event | None" = None,
) -> None:
    """Submit a single turn; stream the reply as TTS while it generates.

    The user can press Space at any time to interrupt: the agent task
    is cancelled on the daemon, any queued TTS chunks are discarded,
    the playback stream is closed, and the function returns so the
    caller can read the next user input.
    """
    from . import render
    from .keypress import install_keypress_handler

    final_text_parts: list[str] = []
    tts = _TTSSpeaker(tts_backend) if tts_backend is not None else None
    srenderer = render.StreamingRenderer() if tts is not None else None

    current_task_id: list = [None]  # set by on_task below
    interrupted: list = [False]      # set by keypress handler

    def on_event(ev: EventMessage) -> None:
        if ev.event != "agent.text":
            return
        data = ev.data or {}
        chunk = data.get("text", "")
        if not chunk:
            return
        if data.get("delta"):
            sys.stdout.write(chunk)
            sys.stdout.flush()
            if srenderer is not None:
                for speakable in srenderer.feed(chunk):
                    if tts is not None and not interrupted[0]:
                        tts.submit(speakable)
        else:
            final_text_parts.append(chunk)

    def on_done(d: TaskDone) -> None:
        if not done_future.done():
            done_future.get_loop().call_soon_threadsafe(done_future.set_result, d)

    def on_task(task_obj) -> None:
        current_task_id[0] = task_obj.id

    client.on_event(on_event)
    client.on_done(on_done)
    client.on_task(on_task)

    done_future: asyncio.Future = asyncio.get_event_loop().create_future()

    def _trigger_interrupt() -> None:
        interrupted[0] = True
        tid = current_task_id[0]
        if tid is not None:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(client.cancel(tid), loop)
        if tts is not None:
            tts.interrupt()
        # Tell the recorder to discard the in-flight audio so the key
        # click noise doesn't get sent to the agent.
        if record_abort is not None:
            record_abort.set()
        sys.stderr.write("\n[interrupted]\n")
        sys.stderr.flush()

    # Keypress handler is installed by _run_mic_mode, which passes
    # us a record_abort to discard the next recording.
    pass

    try:
        await client.submit(input_text=text, model=model)

        # Wait for done OR cancel_event OR keypress (legacy path).
        while True:
            done_task = asyncio.ensure_future(_await_done(done_future))
            if record_abort is not None and record_abort.is_set():
                # Cancel was requested via the mic keypress handler.
                # Wait a moment for the daemon to acknowledge, then return.
                pass  # fall through to the existing interrupt path
            press_task = asyncio.ensure_future(_await_press(keypress_handle))
            try:
                done_set, _ = await asyncio.wait(
                    {done_task, press_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                # The done future was cancelled (e.g. by the daemon
                # acknowledging our cancel). Treat as interrupted.
                interrupted[0] = True
                break
            finally:
                for t in (done_task, press_task):
                    if not t.done():
                        t.cancel()

            if done_task.done():
                try:
                    done: TaskDone = done_task.result()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    # Cancelled or already-cleared.
                    interrupted[0] = True
                    done = None
                    break
                break

            # Interrupted via keypress. Tell the daemon to stop the
            # task and break out of the wait loop. The TTS was
            # already interrupted by _trigger_interrupt.
            if current_task_id[0] is not None:
                try:
                    await client.cancel(current_task_id[0])
                except Exception:
                    pass
            # Give the daemon a brief moment to acknowledge.
            try:
                done = await asyncio.wait_for(done_future, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                done = None
            break
    except asyncio.CancelledError:
        # Outer cancellation (e.g. parent task cancelled). Treat as
        # interrupted and return to the mic loop.
        interrupted[0] = True
        return
    except Exception as exc:
        print(f"\n[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return
    finally:
        # Keypress handle is owned by _run_mic_mode; nothing to do here.
        pass

    sys.stdout.write("\n")
    sys.stdout.flush()

    if tts is not None and not interrupted[0]:
        await tts.drain()

    if interrupted[0]:
        return
    if done is None:
        return
    if done.error:
        print(f"[error] {done.error}", file=sys.stderr)
    elif done.cancelled:
        print("[cancelled]")
    else:
        if srenderer is None and tts is not None:
            full = "".join(final_text_parts).strip()
            if full:
                speakable = render.render_for_speech(full)
                if speakable:
                    tts.submit(speakable)
                    await tts.drain()
        elif srenderer is not None:
            rest = srenderer.flush()
            if rest and tts is not None:
                speakable = render.render_for_speech(rest)
                if speakable:
                    tts.submit(speakable)
                    await tts.drain()
        print(f"[done in {done.iterations} iteration(s)]")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hyusk voice",
        description="Voice/text client for the Hyusk daemon.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--text", action="store_true", help="Read input from stdin (default).")
    mode.add_argument(
        "--mic",
        action="store_true",
        help="Capture from microphone (requires sounddevice + an STT backend).",
    )
    p.add_argument("--model", default=None, help="Override the LLM model.")
    p.add_argument("--host", default=None, help="Daemon host.")
    p.add_argument("--port", type=int, default=None, help="Daemon port.")
    p.add_argument(
        "--no-tts",
        action="store_true",
        help="Do not use TTS (just print the reply).",
    )
    p.add_argument(
        "--tts-backend",
        choices=["say", "kokoro", "openai", "none"],
        default=None,
        help="Override the TTS backend for this run.",
    )
    p.add_argument(
        "--tts-voice",
        default=None,
        help="Override the TTS voice for this run.",
    )
    return p


def _load_voice_config() -> tuple[tts.TTSConfig, str]:
    """Read voice.* keys from the user config file."""
    import tomllib

    from ..config.config import user_config_dir

    cfg = tts.TTSConfig()
    stt_name = ""
    try:
        p = user_config_dir() / "config.toml"
        if p.exists():
            with p.open("rb") as f:
                data = tomllib.load(f).get("voice", {})
            cfg.backend = data.get("tts_backend", "")
            cfg.voice = data.get("tts_voice", "")
            cfg.openai_voice = data.get("openai_voice", cfg.openai_voice)
            stt_name = data.get("stt_backend", "")
    except Exception:
        pass
    return cfg, stt_name


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    cfg = Config.load()
    host = args.host or cfg.daemon.host
    port = args.port or cfg.daemon.port

    # TTS selection: CLI flag > config file > default.
    voice_cfg, _ = _load_voice_config()
    if args.tts_backend:
        voice_cfg.backend = args.tts_backend
    if args.tts_voice:
        voice_cfg.voice = args.tts_voice
    tts_backend = None if args.no_tts else tts.select_backend(voice_cfg)

    async def _amain() -> int:
        client = DaemonClient(host, port)
        try:
            await client.connect()
        except Exception as exc:
            print(f"[voice] cannot connect to daemon at {host}:{port}: {exc}", file=sys.stderr)
            return 1
        try:
            if args.mic:
                return await _run_mic_mode(client, args.model, tts_backend)
            return await _run_text_mode(client, args.model, tts_backend)
        finally:
            await client.close()

    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
