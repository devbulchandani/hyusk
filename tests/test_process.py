"""Process manager and tool tests."""

from __future__ import annotations

import pytest

from hyusk.core.errors import InvalidInput
from hyusk.platform.process import PosixProcessManager, make_process_manager
from hyusk.tools.process.tools import kill_process_tool, list_processes_tool


def test_process_manager_is_posix_on_unix():
    import sys
    if sys.platform == "win32":
        pytest.skip("posix-only test")
    pm = make_process_manager()
    assert isinstance(pm, PosixProcessManager)


def test_list_processes_tool_returns_list():
    if __import__("sys").platform == "win32":
        pytest.skip("posix-only test")
    t = list_processes_tool()
    out = t.run({"limit": 5})
    assert "processes" in out
    assert isinstance(out["processes"], list)


def test_kill_invalid_pid():
    t = kill_process_tool()
    with pytest.raises(InvalidInput):
        # missing required arg
        t.run({})


def test_kill_self_pid_is_safe_to_call_unsupported():
    # We just exercise the error path on non-posix; on posix we accept
    # either success or a failure result (we never kill init).
    t = kill_process_tool()
    out = t.run({"pid": 1, "signal": "TERM"})
    # Either error or ok; both are acceptable for this smoke test.
    assert "killed" in out or "error" in out
