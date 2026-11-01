import json
import logging
import sys
from datetime import datetime, timezone

LOG = logging.getLogger("scytal")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            payload["user_id"] = str(record.user_id)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def log_event(msg: str, request_id: str | None = None, **fields) -> None:
    extra = {k: v for k, v in fields.items()}
    extra["request_id"] = request_id
    LOG.info(msg, extra=extra)
