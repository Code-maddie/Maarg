"""Logging setup.

One call to :func:`configure_logging` at startup wires the root logger and
uvicorn's own loggers to the same handler, so application logs and server
logs come out in a single consistent stream.
"""

import json
import logging
import sys
from typing import Any, Dict

from app.core.config import settings

# Attributes present on every LogRecord; anything else was attached by the
# caller via `extra=` and belongs in the structured payload.
_RESERVED_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"asctime", "message", "taskName"}

_TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Renders records as single-line JSON for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, _DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Installs a single stdout handler on the root logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if settings.log_json
        else logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT)
    )

    level = getattr(logging, settings.log_level, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; drop them so records propagate to root
    # instead of being printed twice in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Returns a module-scoped logger."""
    return logging.getLogger(name)
