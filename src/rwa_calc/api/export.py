"""
Result export utilities for RWA Calculator.

Pipeline position:
    CalculationResponse -> ResultExporter -> Parquet / CSV / Excel files

Key responsibilities:
- Export calculation results to Parquet files (one per dataset)
- Export calculation results to CSV files (one per dataset)
- Export calculation results to multi-sheet Excel workbooks
- Provide a unified export interface regardless of output format

The exporter reads from cached parquet files via CalculationResponse's
lazy scan accessors, so no redundant in-memory materialisation occurs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.api.models import CalculationResponse

logger = logging.getLogger(__name__)


# =============================================================================
# Export Result
# =============================================================================


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


# =============================================================================
# Result Exporter
# =============================================================================


class ResultExporter:
    """
    Exports RWA calculation results to various file formats.

    Reads from CalculationResponse's cached parquet files and writes
    to the requested output format. Supports multi-dataset exports
    (results, summary by class, summary by approach).

    Usage:
        exporter = ResultExporter()
        result = exporter.export_to_parquet(response, Path("output/"))
        result = exporter.export_to_csv(response, Path("output/"))
        result = exporter.export_to_excel(response, Path("output/results.xlsx"))
    """

    def export_to_parquet(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to Parquet files in the given directory.

        Creates one file per dataset: results.parquet, summary_by_class.parquet,
        summary_by_approach.parquet.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write parquet files into

        Returns:
            ExportResult with list of written files and total row count
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0

        # Main results
        results_df = response.scan_results().collect()
        results_path = output_dir / "results.parquet"
        results_df.write_parquet(results_path)
        files.append(results_path)
        total_rows += len(results_df)

        # Summary by class
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()
            class_path = output_dir / "summary_by_class.parquet"
            class_df.write_parquet(class_path)
            files.append(class_path)

        # Summary by approach
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()
            approach_path = output_dir / "summary_by_approach.parquet"
            approach_df.write_parquet(approach_path)
            files.append(approach_path)

        return ExportResult(format="parquet", files=files, row_count=total_rows)

    def export_to_csv(
        self,
        response: CalculationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """
        Export results to CSV files in the given directory.

        Creates one file per dataset: results.csv, summary_by_class.csv,
        summary_by_approach.csv.

        Args:
            response: CalculationResponse with cached results
            output_dir: Directory to write CSV files into

        Returns:
            ExportResult with list of written files and total row count
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0

        # Main results
        results_df = response.scan_results().collect()
        results_path = output_dir / "results.csv"
        results_df.write_csv(results_path)
        files.append(results_path)
        total_rows += len(results_df)

        # Summary by class
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()
            class_path = output_dir / "summary_by_class.csv"
            class_df.write_csv(class_path)
            files.append(class_path)

        # Summary by approach
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()
            approach_path = output_dir / "summary_by_approach.csv"
            approach_df.write_csv(approach_path)
            files.append(approach_path)

        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_to_excel(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """
        Export results to a multi-sheet Excel workbook.

        Creates sheets: "Results", "Summary by Class", "Summary by Approach".
        Requires the xlsxwriter package (Polars dependency for write_excel).

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = (
                "Excel export requires 'xlsxwriter'. "
                "Install it with: uv add xlsxwriter"
            )
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_rows = 0

        # Collect all datasets
        results_df = response.scan_results().collect()
        total_rows += len(results_df)

        class_df: pl.DataFrame | None = None
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()

        approach_df: pl.DataFrame | None = None
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()

        # Write to Excel with multiple sheets using xlsxwriter workbook
        import xlsxwriter as xw

        workbook = xw.Workbook(str(output_path))
        try:
            # Write main results sheet
            results_df.write_excel(
                workbook=workbook,
                worksheet="Results",
                autofit=True,
            )

            # Write summary by class sheet
            if class_df is not None and len(class_df) > 0:
                class_df.write_excel(
                    workbook=workbook,
                    worksheet="Summary by Class",
                    autofit=True,
                )

            # Write summary by approach sheet
            if approach_df is not None and len(approach_df) > 0:
                approach_df.write_excel(
                    workbook=workbook,
                    worksheet="Summary by Approach",
                    autofit=True,
                )
        finally:
            workbook.close()

        return ExportResult(
            format="excel",
            files=[output_path],
            row_count=total_rows,
        )
