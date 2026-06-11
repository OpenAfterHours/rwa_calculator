"""
Observability infrastructure for the RWA Calculator.

Pipeline position:
    Cross-cutting — imported by engine, api, and ui layers. Not part of the
    regulatory-calculation pipeline itself.

Key responsibilities:
- Central `configure_logging` entry point (stdlib-only, idempotent)
- Per-run correlation IDs exposed as a contextvar
- Stage-timing context manager emitting structured entry/exit records
- Text and JSON formatters for human-readable and audit-friendly output
- Opt-in audit-cache writer (`sink_audit` / `prune_audit_cache`)

References:
- docs/specifications/observability.md
- docs/specifications/audit-cache.md
"""

from __future__ import annotations

from rwa_calc.observability.audit_cache import prune_audit_cache, sink_audit
from rwa_calc.observability.context import (
    RunIdFilter,
    bind_run_id,
    clear_run_id,
    current_run_id,
    new_run_id,
    stage_timer,
)
from rwa_calc.observability.formatters import JsonFormatter, TextFormatter
from rwa_calc.observability.logging_setup import configure_logging, get_logger

__all__ = [
    "JsonFormatter",
    "RunIdFilter",
    "TextFormatter",
    "bind_run_id",
    "clear_run_id",
    "configure_logging",
    "current_run_id",
    "get_logger",
    "new_run_id",
    "prune_audit_cache",
    "sink_audit",
    "stage_timer",
]
