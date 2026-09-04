"""Non-blocking keypress detection for the voice client.

On macOS and Linux, this uses ``termios`` + ``select`` to poll stdin
without blocking. On Windows, it falls back to a polling loop using
``msvcrt.kbhit()``.

The interrupt key defaults to Space (a single byte: 0x20). The
typical UX is: while the agent is generating or speaking, press Space
to cancel the current turn and start listening for a new prompt.
"""

from __future__ import annotations

import os
import sys
from typing import Callable


# Default interrupt key (Space).
DEFAULT_INTERRUPT_KEY = b" "


class _Keypress:
    """Context manager that puts the terminal into cbreak mode.

    While inside the context, ``poll()`` returns the key if one was
    pressed, else ``None``. Restores the original terminal mode on
    exit.
    """

    def __init__(self, fd: int = 0) -> None:
        self._fd = fd
        self._restore: list | None = None

    def __enter__(self) -> "_Keypress":
        if sys.platform == "win32":
            # msvcrt is set up lazily on first poll; nothing to do here.
            return self
        try:
            import termios
            import tty
        except ImportError:
            return self
        try:
            self._restore = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:
            self._restore = None
        return self

    def __exit__(self, *exc_info) -> None:
        if self._restore is not None and sys.platform != "win32":
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._restore)
            except Exception:
                pass
        return None

    def poll(self) -> bytes | None:
        """Return the next pressed key as a bytes object, or None.

        Does not block. Returns at most one key per call.
        """
        if sys.platform == "win32":
            try:
                import msvcrt

                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    return bytes([ch]) if isinstance(ch, int) else ch
            except Exception:
                pass
            return None
        # POSIX: use select + read.
        try:
            import select

            rlist, _, _ = select.select([self._fd], [], [], 0)
            if not rlist:
                return None
            data = os.read(self._fd, 1)
            return data if data else None
        except Exception:
            return None


def install_keypress_handler(
    on_interrupt: Callable[[], None] | None = None,
    fd: int = 0,
) -> tuple["_Keypress", threading.Thread]:
    """Install a background thread that polls stdin and fires on_interrupt
    when Space is pressed.

    Returns a tuple of (keypress_ctx, watcher_thread). The caller is
    responsible for keeping both alive (e.g. via a context manager) and
    for stopping the thread on exit.

    The watcher thread runs in a loop calling ``poll()`` every 50ms. On
    Space, it calls ``on_interrupt()``.
    """
    import threading

    ctx = _Keypress(fd)
    stop_event = threading.Event()
    keypressed_event = threading.Event()

    def watcher():
        ctx.__enter__()
        try:
            while not stop_event.is_set():
                key = ctx.poll()
                if key == DEFAULT_INTERRUPT_KEY:
                    keypressed_event.set()
                    if on_interrupt is not None:
                        try:
                            on_interrupt()
                        except Exception:
                            pass
                # Always sleep a tick to avoid pegging CPU.
                import time
                time.sleep(0.02)
        finally:
            ctx.__exit__(None, None, None)

    thread = threading.Thread(target=watcher, daemon=True)

    class _Handle:
        def stop(self) -> None:
            stop_event.set()
            thread.join(timeout=1.0)
            keypressed_event.set()

        def was_pressed(self) -> bool:
            return keypressed_event.is_set()

        def clear(self) -> None:
            keypressed_event.clear()

    # We can't return the handle from a tuple; expose it on the thread
    # object so callers can ``thread.handle.stop()``.
    handle = _Handle()
    thread.handle = handle  # type: ignore[attr-defined]
    thread.start()
    # We return a small wrapper tuple that includes the handle.
    return (ctx, thread, handle)
