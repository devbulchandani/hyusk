"""Git tool smoke tests against the local repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hyusk.tools.git.tools import git_branch_tool, git_log_tool, git_status_tool


@pytest.fixture
def git_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y.z"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hi")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_status_ok(git_repo: Path):
    t = git_status_tool()
    out = t.run({"cwd": str(git_repo)})
    assert "raw" in out


def test_log(git_repo: Path):
    t = git_log_tool()
    out = t.run({"cwd": str(git_repo), "limit": 5})
    assert "commits" in out
    assert len(out["commits"]) >= 1


def test_branch(git_repo: Path):
    t = git_branch_tool()
    out = t.run({"cwd": str(git_repo)})
    assert out["branch"] == "main"
