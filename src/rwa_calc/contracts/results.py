"""
Result DTOs shared across the export and reporting layers.

Pipeline position:
    OutputAggregator -> api / reporting consumers (ExportResult describes the
    outcome of writing results to disk in any supported format)

Key responsibilities:
- Define result data-transfer objects that both the api layer and the
  reporting layer reference, so that neither has to import the other.

`ExportResult` previously lived in ``rwa_calc.api.export``, which forced
``contracts/protocols.py`` and the reporting generators to import from the
api layer — a layering inversion (contracts and reporting must not depend on
api). It is re-exported from ``rwa_calc.api.export`` for backwards
compatibility. Enforced by ``scripts/arch_check.py`` check 12
(import direction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExportResult:
    """
    Result of an export operation.

    Attributes:
        format: Export format used ("parquet", "csv", "excel")
        files: List of files written
        row_count: Total number of data rows exported across all datasets
    """

    format: str
    files: list[Path] = field(default_factory=list)
    row_count: int = 0
