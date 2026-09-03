"""Filesystem tools: list_directory, read_file, write_file."""

from __future__ import annotations

import os
from pathlib import Path

from ...core.errors import FileNotFound, InvalidInput
from ...platform.filesystem import read_text, safe_path, write_text
from ..base import READ, WRITE, Tool


def _schema(props: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


def list_directory_tool() -> Tool:
    def execute(args: dict) -> dict:
        path = args["path"]
        try:
            p = safe_path(path, must_exist=True)
        except FileNotFound as exc:
            return {"error": str(exc)}
        if not p.is_dir():
            return {"error": f"not a directory: {p}"}
        items: list[dict] = []
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
                items.append(
                    {
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": st.st_size,
                        "modified": int(st.st_mtime),
                    }
                )
            except OSError:
                continue
        return {"path": str(p), "entries": items}

    return Tool(
        name="list_directory",
        description="List the entries of a directory. Returns name, type, size, modified.",
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        permission=READ,
        execute=execute,
    )


def read_file_tool(*, max_bytes: int = 1_000_000) -> Tool:
    def execute(args: dict) -> dict:
        path = args["path"]
        offset = args.get("offset")
        try:
            p = safe_path(path, must_exist=True)
        except FileNotFound as exc:
            return {"error": str(exc)}
        if not p.is_file():
            return {"error": f"not a file: {p}"}
        try:
            text = read_text(p, max_bytes=max_bytes)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        if isinstance(offset, int) and offset > 0:
            # best-effort line offset for very large files
            lines = text.splitlines()
            text = "\n".join(lines[offset:])
        return {"path": str(p), "content": text}

    return Tool(
        name="read_file",
        description="Read a UTF-8 text file. Truncates very large files. Optional line offset.",
        input_schema=_schema(
            {"path": {"type": "string"}, "offset": {"type": "integer"}},
            ["path"],
        ),
        permission=READ,
        execute=execute,
    )


def write_file_tool() -> Tool:
    def execute(args: dict) -> dict:
        path = args["path"]
        content = args["content"]
        if not isinstance(content, str):
            raise InvalidInput("write_file: 'content' must be a string")
        p = Path(os.path.expanduser(path))
        try:
            write_text(p, content)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {"path": str(p), "bytes_written": len(content.encode("utf-8"))}

    return Tool(
        name="write_file",
        description="Write a UTF-8 text file, creating parent directories as needed.",
        input_schema=_schema(
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        permission=WRITE,
        execute=execute,
    )


def register_filesystem_tools(registry) -> None:
    registry.register(list_directory_tool())
    registry.register(read_file_tool())
    registry.register(write_file_tool())
