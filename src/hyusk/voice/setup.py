"""Voice setup and diagnostics.

Provides two CLI-friendly helpers:

* :func:`doctor` — check the current voice stack and report what's
  working and what's missing. Always returns a printable report; never
  raises.

* :func:`setup` — same checks but in a "what to install" format that
  can be followed by the user step-by-step.

These are also exposed as ``hyusk voice doctor`` and ``hyusk voice setup``
via :func:`register_commands`.
"""

from __future__ import annotations

import logging
import shutil
import sys

logger = logging.getLogger("hyusk.voice.setup")


def _check(label: str, ok: bool, hint: str = "") -> tuple[str, str]:
    """Return (status, message) for a single check."""
    if ok:
        return ("OK", f"  [OK]   {label}")
    msg = f"  [FAIL] {label}"
    if hint:
        msg += f"\n          hint: {hint}"
    return ("FAIL", msg)


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def doctor() -> int:
    """Check the voice stack and print a report. Returns 0 if fully ready."""
    print("Hyusk voice doctor")
    print("=" * 60)
    failures = 0

    # Python
    print(f"  [OK]   Python {sys.version.split()[0]} on {sys.platform}")

    # Audio device (mic)
    try:
        import sounddevice as sd
        try:
            devs = sd.query_devices()
            inputs = [d for d in devs if d.get("max_input_channels", 0) > 0]
            if inputs:
                print(f"  [OK]   microphone: {len(inputs)} input device(s) found")
            else:
                print("  [FAIL] microphone: no input device found")
                failures += 1
        except Exception as exc:
            print(f"  [FAIL] microphone: {exc}")
            failures += 1
    except ImportError:
        print("  [FAIL] sounddevice not installed")
        print("          hint: uv pip install sounddevice")
        failures += 1

    # Speaker
    try:
        import sounddevice as sd
        try:
            devs = sd.query_devices()
            outputs = [d for d in devs if d.get("max_output_channels", 0) > 0]
            if outputs:
                print(f"  [OK]   speaker: {len(outputs)} output device(s) found")
            else:
                print("  [FAIL] speaker: no output device found")
                failures += 1
        except Exception:
            pass
    except ImportError:
        pass  # already reported

    # TTS backends
    print("\nTTS:")
    from .tts.kokoro import KokoroBackend
    from .tts.say_backend import SayBackend
    from .tts.openai_tts import OpenAITTSBackend
    from .tts.noop import NoOpBackend

    say = SayBackend()
    if say.is_available():
        print(f"  [OK]   say: available (macOS)")
    else:
        print(f"  [-]    say: not available (not macOS)")

    kokoro = KokoroBackend()
    if kokoro.is_available():
        print(f"  [OK]   kokoro: package installed")
        try:
            import subprocess as _sp
            r = _sp.run(
                ["uv", "run", "python", "-c",
                 "from hyusk.voice.tts.kokoro import KokoroBackend; "
                 "KokoroBackend()._ensure_model()"],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0:
                print(f"  [OK]   kokoro: model loaded (default voice: {kokoro._voice})")
            else:
                err = (r.stderr or b"").decode("utf-8", errors="replace").strip()[-200:]
                print(f"  [FAIL] kokoro: model failed to load: {err}")
                failures += 1
        except _sp.TimeoutExpired:
            print(f"  [WARN] kokoro: model download timed out (>60s)")
            print("          the model will be downloaded on first use")
        except Exception as exc:
            print(f"  [FAIL] kokoro: {exc}")
            failures += 1
    else:
        print(f"  [FAIL] kokoro: not installed")
        print("          hint: uv pip install kokoro-onnx")
        failures += 1

    openai = OpenAITTSBackend()
    if openai.is_available():
        print(f"  [OK]   openai: TTS API key present")
    else:
        print(f"  [-]    openai: TTS API key not set")
        print(f"          hint: hyusk config set llm.api_key <KEY>")

    # STT backends
    print("\nSTT:")
    from .stt.whisper_cpp_stt import WhisperCppSTT
    from .stt.whisper_api import WhisperAPI

    wcpp = WhisperCppSTT()
    if wcpp.is_available():
        print(f"  [OK]   whisper.cpp: package installed")
        # Try to load the model in a subprocess with a timeout so a slow
        # download never hangs the doctor.
        try:
            import subprocess as _sp
            r = _sp.run(
                ["uv", "run", "python", "-c",
                 "from hyusk.voice.stt.whisper_cpp_stt import WhisperCppSTT; "
                 "WhisperCppSTT()._ensure_model()"],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0:
                print(f"  [OK]   whisper.cpp: model loaded (default: {wcpp._model_name})")
            else:
                err = (r.stderr or b"").decode("utf-8", errors="replace").strip()[-200:]
                print(f"  [FAIL] whisper.cpp: model failed to load: {err}")
                failures += 1
        except _sp.TimeoutExpired:
            print(f"  [WARN] whisper.cpp: model download timed out (>60s)")
            print("          the model will be downloaded on first use")
        except Exception as exc:
            print(f"  [FAIL] whisper.cpp: {exc}")
            failures += 1
    else:
        print(f"  [FAIL] whisper.cpp: not installed")
        print("          hint: uv pip install pywhispercpp")
        failures += 1

    api = WhisperAPI()
    if api.is_available():
        print(f"  [OK]   whisper-api: API key present")
    else:
        print(f"  [-]    whisper-api: no API key (ok if whisper.cpp works)")

    print()
    if failures == 0:
        print("Voice stack is ready.")
        return 0
    print(f"Voice stack has {failures} issue(s). See hints above.")
    return 1


def setup() -> int:
    """Print a step-by-step guide to getting the voice stack working."""
    print("Hyusk voice setup")
    print("=" * 60)
    print()
    print("Recommended install (one shot):")
    print("    uv pip install sounddevice numpy scipy pywhispercpp kokoro-onnx")
    print()
    print("Optional: pick a STT model. Defaults:")
    print("  - whisper_cpp backend -> base.en (74M, English, fast)")
    print("  - kokoro TTS          -> af_sarah (default voice)")
    print()
    print("Set your backend choices:")
    print("    hyusk config set voice.tts_backend   kokoro")
    print("    hyusk config set voice.stt_backend   whisper_cpp")
    print("    hyusk config set voice.tts_voice     af_sarah")
    print()
    print("Set your LLM credentials (any OpenAI-compatible endpoint):")
    print("    hyusk config set llm.provider openai")
    print("    hyusk config set llm.api_key  <KEY>")
    print("    hyusk config set llm.base_url  https://openrouter.ai/api/v1")
    print("    hyusk config set llm.model     anthropic/claude-3.5-sonnet")
    print()
    print("Then run `hyusk voice doctor` to verify.")
    return 0


def register_commands(subparsers) -> None:
    """Register ``voice setup`` and ``voice doctor`` as CLI subcommands."""
    p = subparsers.add_parser("voice", help="voice utilities (setup, doctor)")
    voice_sub = p.add_subparsers(dest="voice_action", required=True)
    voice_sub.add_parser("setup", help="print a one-time setup guide")
    voice_sub.add_parser("doctor", help="diagnose the voice stack")
    voice_sub.add_parser("test", help="say a test phrase using the current TTS")
