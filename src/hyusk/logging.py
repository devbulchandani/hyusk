"""Structured logging for Hyusk."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from hyusk.config import get_config


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add custom fields
        for key in ["task_id", "agent_id", "tool", "component", "duration_ms", "status"]:
            if hasattr(record, key):
                value = getattr(record, key)
                # Convert UUID to string
                if isinstance(value, UUID):
                    value = str(value)
                log_data[key] = value

        # Add any extra fields from the record
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data)


class RedactingFilter(logging.Filter):
    """Filter to redact sensitive information from logs."""

    SENSITIVE_KEYS = {
        "api_key",
        "token",
        "password",
        "secret",
        "credential",
        "authorization",
        "auth",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive information from log record."""
        if hasattr(record, "extra_fields"):
            record.extra_fields = self._redact_dict(record.extra_fields)
        return True

    def _redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive keys from dictionary."""
        redacted = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = self._redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self._redact_dict(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                redacted[key] = value
        return redacted


class HyuskLogger:
    """Structured logger for Hyusk with context management."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context: dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        """Set context that will be included in all log messages."""
        self.context.update(kwargs)

    def clear_context(self) -> None:
        """Clear the logging context."""
        self.context.clear()

    def _log(self, level: int, message: str, **extra: Any) -> None:
        """Log with structured data."""
        # Merge context and extra fields
        fields = {**self.context, **extra}

        # Create log record with extra fields
        self.logger.log(level, message, extra={"extra_fields": fields})

    def debug(self, message: str, **extra: Any) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **extra)

    def info(self, message: str, **extra: Any) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **extra)

    def critical(self, message: str, **extra: Any) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, message, **extra)

    def exception(self, message: str, **extra: Any) -> None:
        """Log exception with traceback."""
        fields = {**self.context, **extra}
        self.logger.exception(message, extra={"extra_fields": fields})


def setup_logging(config: Any | None = None) -> None:
    """Setup logging configuration for Hyusk."""
    if config is None:
        config = get_config().logging

    # Create log directory
    log_path = Path(config.file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)

    # File handler (JSON structured)
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(getattr(logging, config.level.upper()))

    if config.format == "json":
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(console_format)

    # Add redacting filter
    redacting_filter = RedactingFilter()
    file_handler.addFilter(redacting_filter)

    # Add handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> HyuskLogger:
    """Get a logger instance for a component."""
    return HyuskLogger(name)
