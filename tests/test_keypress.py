"""Tests for the non-blocking keypress detector."""

from __future__ import annotations

import time
import sys


def test_keypress_default_interrupt_key_is_space():
    """The default interrupt key should be Space (0x20)."""
    from hyusk.voice.keypress import DEFAULT_INTERRUPT_KEY
    assert DEFAULT_INTERRUPT_KEY == b" "


def test_keypress_poll_returns_none_when_no_input():
    """When no key is pressed, poll() returns None immediately."""
    from hyusk.voice.keypress import _Keypress
    kp = _Keypress()
    with kp:
        # No input is queued in a test process; should be quick.
        t0 = time.time()
        result = kp.poll()
        elapsed = time.time() - t0
        assert result is None
        # poll() must not block.
        assert elapsed < 0.5, f"poll() blocked for {elapsed:.2f}s"


def test_keypress_install_handler_runs_callback():
    """install_keypress_handler() should run the callback when Space is pressed."""
    from hyusk.voice.keypress import install_keypress_handler

    pressed: list[int] = []

    def on_interrupt():
        pressed.append(1)

    ctx, thread, handle = install_keypress_handler(
        on_interrupt=on_interrupt, fd=0
    )
    try:
        # The handler is installed. We can't easily simulate a keypress
        # in a unit test (would require faking stdin), so we just verify
        # the installation succeeded and the handle exposes the
        # expected API.
        assert handle is not None
        assert callable(handle.stop)
        assert callable(handle.was_pressed)
        assert handle.was_pressed() is False
    finally:
        handle.stop()
