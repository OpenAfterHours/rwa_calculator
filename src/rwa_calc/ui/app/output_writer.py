"""
Write selected calculation-result formats into a user-chosen output folder.

Pipeline position:
    CalculationResponse -> write_selected_formats -> <folder>/rwa_export_<run_id>/

Key responsibilities:
- Normalise the directory-vs-file asymmetry of the export wrappers: parquet/csv
  write a set of dataset files into a directory; excel/corep write one workbook.
- Isolate every run/save in a run-stamped subfolder so a re-export can never
  silently clobber a different run's files, and two concurrent writes (the
  worker pool runs up to four) cannot race on the same fixed filenames.
- Convert a missing xlsxwriter (which the exporters *raise*) or any OSError into
  a per-format user-facing message rather than raising — the UI surfaces the
  outcome, never a 500.

This is the single write surface shared by the on-demand save route and the
calc-time worker, so the two paths can never drift.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rwa_calc.api.models import CalculationResponse
    from rwa_calc.contracts.results import ExportResult

logger = logging.getLogger(__name__)

# Workbook filenames for the single-file (file-form) exporters.
_EXCEL_NAME = "rwa_results.xlsx"
_COREP_NAME = "rwa_corep.xlsx"

# Message shown when excel/corep is requested but xlsxwriter is not installed.
_XLSX_HINT = "Excel/COREP export needs xlsxwriter — install it with 'uv add xlsxwriter'."


@dataclass(frozen=True, slots=True)
class OutputWriteResult:
    """
    Outcome of writing the selected formats to a folder.

    Attributes:
        folder: The resolved absolute run-stamped subfolder written into.
        files: Every file successfully written (absolute paths).
        errors: One user-facing message per format that failed (never raised).
    """

    folder: str
    files: tuple[Path, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when at least one file was written and nothing failed."""
        return bool(self.files) and not self.errors


def write_selected_formats(
    response: CalculationResponse,
    folder: Path,
    formats: Sequence[str],
    *,
    run_id: str,
) -> OutputWriteResult:
    """
    Write each selected format into ``folder/rwa_export_<run_id>/``.

    Each format is written independently: a failure in one (xlsxwriter missing
    for excel/corep, or a permission/disk error) is captured as a message and the
    others still proceed. Never raises for an export/IO failure.

    Args:
        response: The completed run to export.
        folder: The user-chosen output folder (a run-stamped subfolder is made).
        formats: Any of ``parquet``, ``csv``, ``excel``, ``corep`` (order kept).
        run_id: The run identifier, used to stamp the isolating subfolder.

    Returns:
        OutputWriteResult with the resolved subfolder, written files and errors.
    """
    subdir = (folder / f"rwa_export_{run_id}").resolve()
    files: list[Path] = []
    errors: list[str] = []
    for fmt in _ordered_unique(formats):
        try:
            files.extend(_write_one(response, fmt, subdir))
        except ModuleNotFoundError:
            errors.append(f"{fmt}: {_XLSX_HINT}")
        except (OSError, pl.exceptions.PolarsError) as exc:
            errors.append(f"{fmt}: could not export to {subdir} ({exc}).")
            logger.warning("output write failed for %s: %s", fmt, exc)
    return OutputWriteResult(folder=str(subdir), files=tuple(files), errors=tuple(errors))


# =============================================================================
# Private helpers
# =============================================================================


def _write_one(response: CalculationResponse, fmt: str, subdir: Path) -> list[Path]:
    """
    Write a single format into *subdir* and return the files written.

    parquet/csv write their dataset files straight into the directory; excel and
    corep are single workbooks written to a temp name then atomically renamed, so
    a re-save can never shadow a good workbook with a half-written one.
    """
    if fmt == "parquet":
        return list(response.to_parquet(subdir).files)
    if fmt == "csv":
        return list(response.to_csv(subdir).files)
    if fmt == "excel":
        return [_write_workbook(response.to_excel, subdir / _EXCEL_NAME)]
    if fmt == "corep":
        return [_write_workbook(response.to_corep, subdir / _COREP_NAME)]
    raise ValueError(f"unknown export format: {fmt}")


def _write_workbook(writer: Callable[[Path], ExportResult], target: Path) -> Path:
    """Write a single-file workbook atomically (temp + ``os.replace``)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        writer(tmp)
    except (ModuleNotFoundError, OSError, pl.exceptions.PolarsError):
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, target)
    return target


def _ordered_unique(formats: Sequence[str]) -> list[str]:
    """De-duplicate the requested formats while preserving order."""
    return list(dict.fromkeys(formats))
