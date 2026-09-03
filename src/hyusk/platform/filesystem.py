"""Filesystem helpers shared across tools.

Pure utilities. Tools in tools/filesystem/ call into here.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from ..core.errors import FileNotFound, InvalidInput


def safe_path(path: str | os.PathLike[str], *, must_exist: bool = True) -> Path:
    p = Path(os.path.expanduser(str(path))).resolve()
    if must_exist and not p.exists():
        raise FileNotFound(f"no such file or directory: {p}")
    return p


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def read_text(path: Path, *, max_bytes: int = 1_000_000) -> str:
    if not path.exists():
        raise FileNotFound(f"no such file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        with path.open("rb") as f:
            data = f.read(max_bytes)
        text = data.decode("utf-8", errors="replace")
        return text + f"\n... [truncated at {max_bytes} bytes of {size}]"
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_within_any(path: Path, allowed_roots: Iterable[Path]) -> bool:
    roots = [p.resolve() for p in allowed_roots]
    for r in roots:
        if is_within(path, r):
            return True
    return False


def assert_relative(path: str) -> str:
    if path.startswith("~") or os.path.isabs(path):
        raise InvalidInput(f"path must be relative: {path}")
    return path
