"""Voice client.

A standalone process that:
  1. Captures the user's voice (microphone) or reads typed text.
  2. Pushes the transcript to the Hyusk daemon over WebSocket.
  3. Receives the agent's reply and either prints it or speaks it.

Modes
-----

`--text`     Read lines from stdin as if they were speech. Useful for
            CI / headless / when no microphone is available.

`--mic`      Use the system microphone. Requires `sounddevice` (and
            for STT, an external service; we ship a stub).

The voice client uses the same WebSocket protocol as the regular CLI
(`DaemonClient`). Each user turn becomes a `run` message; the agent's
text deltas are accumulated and printed / spoken as a single reply.

Stopping: Ctrl-C interrupts the current TTS playback. Ctrl-D exits.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ..client.client import DaemonClient, EventMessage, TaskDone
from ..config.config import Config


def _short_input(text: str) -> str:
    text = text.strip()
    if len(text) > 200:
        return text[:197] + "..."
    return text


def _read_text_loop() -> list[str]:
    """Read user inputs from stdin. Returns the list of inputs (one per line).

    Each line is treated as a separate turn; an empty line does nothing.
    Ctrl-D / EOF ends the session.
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


async def _run_text_mode(client: DaemonClient, model: str | None) -> int:
    """Text-mode voice client: read input from stdin, send to daemon."""
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
        await _run_turn(client, line, model)
    return 0


async def _run_mic_mode(client: DaemonClient, model: str | None) -> int:
    """Mic mode: use sounddevice to capture audio and STT to transcribe.

    The full audio path is not wired up in V4 (no STT engine bundled)
    so this function delegates to a stub that simulates a single
    transcript from a file or a hard-coded string. Users with audio
    hardware can subclass this.
    """
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        print(
            "mic mode requires `sounddevice` (and an STT engine); "
            "falling back to text mode.",
            file=sys.stderr,
            flush=True,
        )
    # Stub: prompt for a transcript
    print("mic mode (stub): enter transcript manually.", flush=True)
    return await _run_text_mode(client, model)


async def _run_turn(client: DaemonClient, text: str, model: str | None) -> None:
    """Submit a single turn and render the reply."""
    final_text_parts: list[str] = []

    def on_event(ev: EventMessage) -> None:
        if ev.event == "agent.text":
            data = ev.data or {}
            chunk = data.get("text", "")
            if data.get("delta"):
                final_text_parts.append(chunk)
                # Stream to stdout in real time.
                sys.stdout.write(chunk)
                sys.stdout.flush()

    client.on_event(on_event)

    done_future: asyncio.Future[TaskDone] = asyncio.get_event_loop().create_future()

    def on_done(d: TaskDone) -> None:
        if not done_future.done():
            done_future.get_loop().call_soon_threadsafe(done_future.set_result, d)

    client.on_done(on_done)

    try:
        await client.submit(input_text=text, model=model)
        done = await asyncio.wait_for(done_future, timeout=600.0)
        sys.stdout.write("\n")
        sys.stdout.flush()
        if done.error:
            print(f"[error] {done.error}", file=sys.stderr)
        elif done.cancelled:
            print("[cancelled]")
        else:
            print(f"[done in {done.iterations} iteration(s)]")
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hyusk voice",
        description="Voice/text client for the Hyusk daemon.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--text",
        action="store_true",
        help="Read input from stdin (default if --mic is not given).",
    )
    mode.add_argument(
        "--mic",
        action="store_true",
        help="Capture from microphone (requires sounddevice + STT).",
    )
    p.add_argument("--model", default=None, help="Override the LLM model.")
    p.add_argument(
        "--host",
        default=None,
        help="Daemon host (default: from HYUSK_DAEMON_HOST or config).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Daemon port (default: from HYUSK_DAEMON_PORT or config).",
    )
    p.add_argument(
        "--no-tts",
        action="store_true",
        help="Do not attempt TTS for replies (just print).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    cfg = Config.load()
    host = args.host or cfg.daemon.host
    port = args.port or cfg.daemon.port

    async def _amain() -> int:
        client = DaemonClient(host, port)
        try:
            await client.connect()
        except Exception as exc:
            print(f"[voice] cannot connect to daemon at {host}:{port}: {exc}", file=sys.stderr)
            return 1
        try:
            if args.mic:
                return await _run_mic_mode(client, args.model)
            return await _run_text_mode(client, args.model)
        finally:
            await client.close()

    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
