"""Allowlisted JSON events: never serialize prompts, tool arguments, or exceptions."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

IDENTITY: ContextVar[dict[str, str] | None] = ContextVar("observation_identity", default=None)
SAFE_FIELDS = frozenset(
    {
        "component",
        "request_id",
        "tenant_id",
        "session_id",
        "event",
        "node",
        "agents",
        "tool",
        "status",
        "error_code",
        "duration_seconds",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "requires_confirmation",
        "approved",
        "source_message_count",
        "route",
        "http_status",
    }
)
logger = logging.getLogger("commerceops.events")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "safe_fields", {"event": "library_log", "component": record.name})
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                **{key: value for key, value in fields.items() if key in SAFE_FIELDS},
            },
            sort_keys=True,
        )


def configure_logging() -> None:
    from commerceops.config import settings

    if not any(getattr(handler, "commerceops_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.commerceops_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())
    for root_handler in root_logger.handlers:
        root_handler.setFormatter(JsonFormatter())
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False


def event(name: str, **fields: Any) -> None:
    logger.info("", extra={"safe_fields": {**(IDENTITY.get() or {}), "event": name, **fields}})
