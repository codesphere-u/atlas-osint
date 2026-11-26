"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization|api[_-]?key|token|password|secret)(\"?\s*[:=]\s*\"?)([^\s\",]+)"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"atl_[A-Za-z0-9_\-]{10,}"),
]


def redact(message: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            message = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", message)
        else:
            message = pattern.sub("[REDACTED]", message)
    return message


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("investigation_id", "source", "request_id", "user_id", "status", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
