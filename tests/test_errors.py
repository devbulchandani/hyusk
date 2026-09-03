"""Logging tests — ensure secrets are scrubbed."""

from __future__ import annotations

import logging

from hyusk.core.logging import SecretFilter, configure_logging, get_logger


def test_secret_filter_scrubs_messages():
    f = SecretFilter()
    rec = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="authorization=Bearer abc123", args=(), exc_info=None,
    )
    assert f.filter(rec)
    assert "***" in rec.msg
    assert "abc123" not in rec.msg


def test_logger_emits():
    configure_logging("WARNING")
    log = get_logger("test")
    # Just exercise the code path.
    log.warning("hi %s", "there")
