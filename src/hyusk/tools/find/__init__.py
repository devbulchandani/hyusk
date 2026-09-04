"""Find files tool.

Searches for files by name pattern within a directory tree, with an
optional content match. Useful for "find where the test for X lives" or
"where is the config file defined".
"""
from __future__ import annotations

import os
from typing import Any

from ...tools.base import READ, Tool


_FIND_TIMEOUT = 5.0  # seconds; do not let the agent lock up the daemon


def _find_files(
    directory: str,
    name_pattern: str = "*",
    content_pattern: str | None = None,
    max_depth: int = 8,
    limit: int = 100,
) -> list[dict]:
    import fnmatch
    import re
    import time

    results: list[dict] = []
    start = time.time()
    base = os.path.abspath(directory)
    if not os.path.isdir(base):
        return [{"error": f"not a directory: {directory}"}]
    rx = re.compile(content_pattern) if content_pattern else None
    depth_root = base.rstrip(os.sep).count(os.sep) + 1
    for root, dirs, files in os.walk(base, followlinks=False):
        if time.time() - start > _FIND_TIMEOUT:
            break
        if max_depth >= 0:
            depth = root.count(os.sep) - depth_root + 1
            if depth > max_depth:
                dirs[:] = []
                continue
        # Skip common noise directories.
        dirs[:] = [
            d for d in dirs
            if d not in ("node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", "dist", "build")
        ]
        for f in files:
            if not fnmatch.fnmatch(f, name_pattern):
                continue
            full = os.path.join(root, f)
            entry = {"path": full, "size": os.path.getsize(full)}
            if rx is not None:
                try:
                    with open(full, "r", errors="replace") as fh:
                        for i, line in enumerate(fh, start=1):
                            if rx.search(line):
                                entry["match_line"] = i
                                entry["match_text"] = line.rstrip()
                                break
                    if "match_line" not in entry:
                        continue
                except OSError:
                    continue
            results.append(entry)
            if len(results) >= limit:
                return results
    return results


def find_files_tool() -> Tool:
    def execute(args: dict) -> dict:
        return {
            "results": _find_files(
                directory=args.get("directory", "."),
                name_pattern=args.get("name_pattern", "*"),
                content_pattern=args.get("content_pattern"),
                max_depth=int(args.get("max_depth", 8)),
                limit=int(args.get("limit", 100)),
            )
        }
    return Tool(
        name="find_files",
        description=(
            "Find files by name pattern, optionally also matching a "
            "content regex. Search a directory recursively up to "
            "max_depth. Returns up to `limit` matches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search (default: cwd)"},
                "name_pattern": {"type": "string", "description": "Glob-style name pattern (e.g. '*.py')"},
                "content_pattern": {"type": "string", "description": "Optional regex to match file contents"},
                "max_depth": {"type": "integer", "description": "Max directory depth (default 8)"},
                "limit": {"type": "integer", "description": "Max results to return (default 100)"},
            },
            "required": [],
        },
        permission=READ,
        execute=execute,
    )


def register_find_tools(registry) -> None:
    registry.register(find_files_tool())
