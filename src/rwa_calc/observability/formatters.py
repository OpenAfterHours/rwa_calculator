"""
Log formatters for the RWA Calculator observability layer.

Pipeline position:
    Cross-cutting — attached to the `rwa_calc` namespace logger's handler by
    `configure_logging`. Not called directly by engine code.

Key responsibilities:
- `TextFormatter`: concise human-readable line format for local runs and
  the marimo server banner
- `JsonFormatter`: single-line JSON records suitable for audit ingestion;
  emits a whitelisted set of record attributes plus any whitelisted extras

References:
- docs/specifications/observability.md
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

_TEXT_FORMAT = "%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s: %(message)s"


class TextFormatter(logging.Formatter):
    """Human-readable text formatter. Run-id placeholder is populated by `RunIdFilter`."""

    def __init__(self) -> None:
        super().__init__(fmt=_TEXT_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")


class JsonFormatter(logging.Formatter):
    """Single-line JSON formatter for audit ingestion.

    Emits a stable core schema and merges a whitelisted set of `extra` keys.
    """

    _EXTRA_WHITELIST: ClassVar[frozenset[str]] = frozenset(
        {
            "stage",
            "elapsed_ms",
            "row_count",
            "framework",
            "permission_mode",
            "log_level",
            "log_format",
            "run_id",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", "-"),
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        for key in self._EXTRA_WHITELIST:
            if key in payload:
                continue
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exc_type"] = exc_type.__name__ if exc_type else None
            payload["exc_message"] = str(exc_value) if exc_value else None
            payload["traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)
