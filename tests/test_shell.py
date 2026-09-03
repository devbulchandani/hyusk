"""Shell tool tests."""

from __future__ import annotations

from hyusk.tools.shell.tools import shell_execute_tool


def test_shell_success():
    t = shell_execute_tool()
    out = t.run({"command": "echo hi"})
    assert out["exit_code"] == 0
    assert "hi" in out["stdout"]


def test_shell_failure():
    t = shell_execute_tool()
    out = t.run({"command": "false"})
    assert out["exit_code"] != 0


def test_shell_timeout_returns_error():
    t = shell_execute_tool()
    # sleep well past the timeout; tool catches and returns an error dict
    out = t.run({"command": "sleep 5", "timeout": 0.2})
    assert "error" in out
