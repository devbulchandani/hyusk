"""CLI helpers for `hyusk config` (V4.1).

Lets the user set/show/delete config values from the command line without
touching environment variables. Values are persisted in
`<user_config>/hyusk/config.toml`.

The CLI never logs API keys. `config show` masks anything whose key
contains `key`, `token`, `secret`, or `password`.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

# Keys whose values are masked when shown.
_SECRET_KEYS = re.compile(r"(key|token|secret|password|auth)", re.IGNORECASE)


def _config_path() -> Path:
    from .config import user_config_dir
    return user_config_dir() / "config.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    # We use tomllib for reading only; for writing we serialize ourselves
    # to keep the dependency set minimal.
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict) or not values:
            continue
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, str):
                # Always quote strings; escape internal quotes.
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{k} = "{escaped}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"{k} = {v}")
            else:
                # Fall back to repr (will be valid TOML for most literals).
                lines.append(f"{k} = {v!r}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


def _walk(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str, bool]]:
    """Yield (dotted_key, value_str, is_secret) tuples for every scalar in `data`."""
    out: list[tuple[str, str, bool]] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        for k, v in values.items():
            dotted = f"{section}.{k}" if not prefix else f"{prefix}.{section}.{k}"
            if isinstance(v, str):
                secret = bool(_SECRET_KEYS.search(k))
                out.append((dotted, v, secret))
            elif isinstance(v, bool):
                out.append((dotted, "true" if v else "false", False))
            elif isinstance(v, (int, float)):
                out.append((dotted, str(v), False))
            elif isinstance(v, dict):
                out.extend(_walk({section: v}, prefix=dotted.split(f".{section}")[0]))
    return out


# ---- public commands ----


def show(mask_secrets: bool = True) -> int:
    """Print the current configuration."""
    from .config import Config
    cfg = Config.load()
    # Show the merged view (file + env). Persisted file first.
    print("=== persisted config ===")
    path = _config_path()
    if path.exists():
        data = _read_toml(path)
        if not data:
            print(f"(empty: {path})")
        else:
            for dotted, value, secret in _walk(data):
                if mask_secrets and secret:
                    print(f"  {dotted} = {_mask(value)}")
                else:
                    print(f"  {dotted} = {value}")
    else:
        print(f"(no file at {path})")

    print()
    print("=== effective config (after env + defaults) ===")
    llm = cfg.llm
    print(f"  llm.provider    = {llm.provider}")
    print(f"  llm.model       = {llm.model}")
    print(f"  llm.base_url    = {llm.base_url or '(default)'}")
    print(f"  llm.api_key     = {_mask(llm.api_key) if mask_secrets and llm.api_key else '(unset)'}")
    print(f"  llm.stream      = {llm.stream}")
    print(f"  agent.max_iterations = {cfg.agent.max_iterations}")
    print(f"  daemon.host     = {cfg.daemon.host}")
    print(f"  daemon.port     = {cfg.daemon.port}")
    print()
    # TTS/STT settings (V4.1).
    tts = _read_toml(path).get("voice", {})
    print("=== voice (V4.1) ===")
    print(f"  voice.tts_backend = {tts.get('tts_backend', 'say (macOS default)')}")
    print(f"  voice.stt_backend = {tts.get('stt_backend', 'mlx-whisper (macOS default) / text fallback')}")
    return 0


def set_value(key: str, value: str) -> int:
    """Set a config value using dotted notation, e.g. `llm.api_key`."""
    if "." not in key:
        print(f"error: key must be dotted (e.g. `llm.api_key`); got: {key!r}", file=sys.stderr)
        return 2
    section, name = key.split(".", 1)
    allowed = {"llm", "agent", "daemon", "voice", "permissions"}
    if section not in allowed:
        print(
            f"warning: setting an unknown section {section!r}; allowed: {sorted(allowed)}",
            file=sys.stderr,
        )
    if name in {"api_key", "key"} and value and not value.startswith("***"):
        # Don't echo the key back.
        print(f"set {key} (len={len(value)})")
    else:
        print(f"set {key} = {value}")
    path = _config_path()
    data = _read_toml(path)
    data.setdefault(section, {})
    data[section][name] = value
    _write_toml(path, data)
    return 0


def unset_value(key: str) -> int:
    """Remove a config value."""
    if "." not in key:
        print(f"error: key must be dotted; got: {key!r}", file=sys.stderr)
        return 2
    section, name = key.split(".", 1)
    path = _config_path()
    data = _read_toml(path)
    if section in data and name in data[section]:
        del data[section][name]
        if not data[section]:
            del data[section]
        _write_toml(path, data)
        print(f"unset {key}")
    else:
        print(f"{key} was not set")
    return 0


def path() -> int:
    """Print the resolved config file path."""
    print(_config_path())
    return 0
