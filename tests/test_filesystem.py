"""Filesystem tool tests."""

from __future__ import annotations

from pathlib import Path

from hyusk.tools.filesystem.tools import (
    list_directory_tool,
    read_file_tool,
    write_file_tool,
)


def test_list_directory(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    t = list_directory_tool()
    out = t.run({"path": str(tmp_path)})
    assert "entries" in out
    names = {e["name"] for e in out["entries"]}
    assert "a.txt" in names and "sub" in names


def test_read_and_write(tmp_path: Path):
    write = write_file_tool()
    read = read_file_tool()
    p = tmp_path / "hello.txt"
    out_w = write.run({"path": str(p), "content": "hello world"})
    assert out_w["bytes_written"] == len(b"hello world")
    out_r = read.run({"path": str(p)})
    assert out_r["content"] == "hello world"


def test_read_missing(tmp_path: Path):
    t = read_file_tool()
    out = t.run({"path": str(tmp_path / "nope.txt")})
    assert "error" in out


def test_read_truncates(tmp_path: Path):
    p = tmp_path / "big.txt"
    p.write_text("a" * 2_000_000)
    t = read_file_tool(max_bytes=1000)
    out = t.run({"path": str(p)})
    assert "truncated" in out["content"]
