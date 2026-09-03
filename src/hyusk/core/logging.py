"""Structured logging for Hyusk.

Use the standard library logging with a small helper that emits JSON-friendly
records so downstream consumers (including future WebSocket clients) can parse
them. Never log API keys, tokens, or other secrets.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

# Names of well-known environment variables that must never be logged.
_SECRET_KEYS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "auth",
)


class SecretFilter(logging.Filter):
    """Filter that scrubs obvious secrets from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for key in _SECRET_KEYS:
                # match e.g. "api_key=..." up to a separator
                idx = 0
                while True:
                    pos = msg.lower().find(key + "=", idx)
                    if pos < 0:
                        break
                    end = pos + len(key) + 1
                    while end < len(msg) and msg[end] not in (" ,;\"'", ""):
                        end += 1
                    msg = msg[: pos + len(key) + 1] + "***" + msg[end:]
                    idx = pos + len(key) + 1 + 3
            record.msg = msg
        if record.args:
            new_args: list[Any] = []
            for a in record.args:
                if isinstance(a, str):
                    s = a
                    for key in _SECRET_KEYS:
                        idx = 0
                        while True:
                            pos = s.lower().find(key + "=", idx)
                            if pos < 0:
                                break
                            end = pos + len(key) + 1
                            while end < len(s) and s[end] not in (" ,;\"'", ""):
                                end += 1
                            s = s[: pos + len(key) + 1] + "***" + s[end:]
                            idx = pos + len(key) + 1 + 3
                    new_args.append(s)
                else:
                    new_args.append(a)
            record.args = tuple(new_args)
        return True


_LOGGER_NAME = "hyusk"
_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the hyusk logger.

    Idempotent so callers can re-run it safely.
    """
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level.upper())
    if not _configured:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(SecretFilter())
        logger.addHandler(handler)
        _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    configure_logging(os.environ.get("HYUSK_LOG_LEVEL", "INFO"))
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)


def log_event(level: int, event: str, **fields: Any) -> None:
    """Emit a structured event line as JSON on the hyusk logger."""
    payload = {"event": event, **fields}
    get_logger("event").log(level, json.dumps(payload, default=str))
