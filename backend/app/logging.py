"""Structured JSON logging with recursive redaction.

Nothing that could identify the owner's bank credentials, tokens, or spending
is allowed into a log line. Redaction runs before serialization, so a value
added by a future `extra=` cannot leak simply because nobody remembered.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

REDACTED = "[redacted]"

SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
    "access_token",
    "public_token",
    # Transaction text is the owner's spending history; never log it.
    "query",
    "search_text",
    "original_description",
    "merchant_name",
)

# Log record attributes that are plumbing rather than event data.
_STANDARD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Recursively replace sensitive values and make the rest serializable."""

    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRIBUTES or key.startswith("_"):
                continue
            payload[key] = REDACTED if _is_sensitive(key) else redact(value)

        if record.exc_info:
            payload["error_type"] = getattr(
                record.exc_info[0], "__name__", "Exception"
            )

        return json.dumps(payload, default=repr)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # These emit request bodies and SQL parameters at DEBUG.
    for noisy in ("aiosqlite", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


__all__ = ["JsonFormatter", "REDACTED", "configure_logging", "redact"]
