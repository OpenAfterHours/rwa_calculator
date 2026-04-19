"""
Idempotent logging configuration for the RWA Calculator.

Pipeline position:
    Cross-cutting — invoked by `CreditRiskCalc.calculate()` and by the marimo
    server at startup. The pipeline orchestrator does NOT call this; it assumes
    handlers already exist and emits through `logging.getLogger(__name__)`.

Key responsibilities:
- Configure a single `StreamHandler` on the `rwa_calc` namespace logger with
  the requested formatter and level. Root logger and third-party loggers are
  left alone.
- Idempotent: repeated calls with identical arguments are no-ops; calls with
  differing arguments swap the handler's formatter/level in place without
  stacking handlers.
- Silence noisy third-party loggers (`polars`, `uvicorn.access`, `fastapi`,
  `asyncio`) at WARNING so the stream stays readable.

References:
- docs/specifications/observability.md
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Literal

from rwa_calc.observability.context import RunIdFilter
from rwa_calc.observability.formatters import JsonFormatter, TextFormatter

if TYPE_CHECKING:
    from typing import TextIO

LogFormat = Literal["text", "json"]

_NAMESPACE = "rwa_calc"
_HANDLER_ATTR = "_rwa_calc_handler"
_NOISY_LIBS: tuple[str, ...] = ("polars", "uvicorn.access", "fastapi", "asyncio")

_configured: tuple[str, str, int] | None = None


def configure_logging(
    level: str = "INFO",
    fmt: LogFormat = "text",
    stream: TextIO | None = None,
) -> None:
    """Configure the `rwa_calc` namespace logger.

    Idempotent: passing the same (level, fmt, stream) twice is a no-op.
    Passing new values swaps the existing handler's formatter/level rather
    than stacking additional handlers.
    """
    global _configured

    normalised_level = _normalise_level(level)
    target_stream = stream if stream is not None else sys.stderr
    signature = (normalised_level, fmt, id(target_stream))
    if _configured == signature:
        return

    namespace_logger = logging.getLogger(_NAMESPACE)
    namespace_logger.setLevel(getattr(logging, normalised_level))
    namespace_logger.propagate = False

    formatter = JsonFormatter() if fmt == "json" else TextFormatter()

    handler = _get_or_create_handler(namespace_logger, target_stream)
    handler.setLevel(getattr(logging, normalised_level))
    handler.setFormatter(formatter)
    _ensure_run_id_filter(handler)

    for noisy in _NOISY_LIBS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = signature


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper around `logging.getLogger` for callers that want a single import point."""
    return logging.getLogger(name)


def _normalise_level(level: str) -> str:
    upper = level.upper()
    if upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"invalid log level: {level!r}")
    return upper


def _get_or_create_handler(
    namespace_logger: logging.Logger,
    target_stream: TextIO,
) -> logging.Handler:
    existing = getattr(namespace_logger, _HANDLER_ATTR, None)
    if isinstance(existing, logging.Handler) and existing in namespace_logger.handlers:
        return existing

    handler = logging.StreamHandler(target_stream)
    namespace_logger.addHandler(handler)
    setattr(namespace_logger, _HANDLER_ATTR, handler)
    return handler


def _ensure_run_id_filter(handler: logging.Handler) -> None:
    if not any(isinstance(f, RunIdFilter) for f in handler.filters):
        handler.addFilter(RunIdFilter())
