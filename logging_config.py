from __future__ import annotations

import contextvars
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)


_LOG_RECORD_RESERVED = {
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
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service_name: str, environment: str) -> None:
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment,
        }

        current_request_id = request_id_var.get()
        if current_request_id:
            data["request_id"] = current_request_id

        # Include fields passed via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED or key.startswith("_"):
                continue
            data[key] = value

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            data["error"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value),
                "stack": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }

        return json.dumps(data, default=str, ensure_ascii=False)


def configure_logging(
    *,
    service_name: str = "my-app",
    environment: str = "local",
    level: str = "INFO",
    disable_hypercorn_access_log: bool = True,
) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            service_name=service_name,
            environment=environment,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())

    if disable_hypercorn_access_log:
        logging.getLogger("hypercorn.access").disabled = True

    logging.getLogger("hypercorn.error").handlers.clear()
    logging.getLogger("hypercorn.error").propagate = True

