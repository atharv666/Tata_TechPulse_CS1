"""Minimal structured logging without a provider or infrastructure dependency."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.security import safe_log_message


class JsonFormatter(logging.Formatter):
    """Render standard log records as newline-delimited JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": safe_log_message(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        for key in ("environment", "project_id", "job_id", "query_id", "build_id", "request_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure the root logger once for API process startup."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named standard-library logger."""
    return logging.getLogger(name)
