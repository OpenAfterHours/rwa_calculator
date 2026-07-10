"""
Result export utilities for RWA Calculator.

Pipeline position:
    CalculationResponse -> ResultExporter -> Parquet / CSV / Excel / COREP / Pillar III

Key responsibilities:
- Export calculation results to Parquet files (one per dataset)
- Export calculation results to CSV files (one per dataset)
- Export calculation results to multi-sheet Excel workbooks
- Generate COREP regulatory reporting templates (C 07.00, C 08.01, C 08.02)
- Generate Pillar III quantitative disclosure templates (OV1, CR4-CR10, CMS1/2, CCR1-8)
- Provide a unified export interface regardless of output format

The exporter reads from cached parquet files via CalculationResponse's
lazy scan accessors, so no redundant in-memory materialisation occurs.
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.results import ExportResult

if TYPE_CHECKING:
    from rwa_calc.api.models import (
        CalculationResponse,
        ComparisonExportResponse,
        ReconciliationResponse,
    )
    from rwa_calc.contracts.config import OutputFloorConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Export Result
# =============================================================================

# ExportResult moved to rwa_calc.contracts.results (layering: contracts and
# reporting must not import api). Re-exported here for backwards compatibility.
__all__ = ["ExportResult", "ResultExporter"]


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

        # Main results (nested columns JSON-encoded so CSV can hold them).
        results_df = response.scan_results().collect()
        results_path = output_dir / "results.csv"
        _csv_safe(results_df).write_csv(results_path)
        files.append(results_path)
        total_rows += len(results_df)

        # Summary by class
        class_lf = response.scan_summary_by_class()
        if class_lf is not None:
            class_df = class_lf.collect()
            class_path = output_dir / "summary_by_class.csv"
            _csv_safe(class_df).write_csv(class_path)
            files.append(class_path)

        # Summary by approach
        approach_lf = response.scan_summary_by_approach()
        if approach_lf is not None:
            approach_df = approach_lf.collect()
            approach_path = output_dir / "summary_by_approach.csv"
            _csv_safe(approach_df).write_csv(approach_path)
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
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
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

    def export_to_corep(
        self,
        response: CalculationResponse,
        output_path: Path,
        *,
        output_floor_config: OutputFloorConfig | None = None,
    ) -> ExportResult:
        """
        Export results as COREP regulatory reporting templates.

        Generates C 07.00 (SA credit risk), C 08.01 (IRB totals),
        and C 08.02 (IRB PD grade breakdown) in a multi-sheet Excel
        workbook following EBA/PRA COREP template structure.

        Why: CRR firms must submit quarterly COREP returns to the PRA.
        This reshapes the calculator's exposure-level results into the
        fixed-format regulatory templates (Regulation (EU) 2021/451).

        Args:
            response: CalculationResponse with cached results
            output_path: Path for the .xlsx output file
            output_floor_config: Optional floor config for reporting
                basis conditionality (Art. 92 para 2A). Gates floor
                indicators and materiality columns on entity type.

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.reporting.corep.generator import COREPGenerator

        generator = COREPGenerator()
        bundle = generator.generate(
            response,
            output_floor_config=output_floor_config,
        )
        return generator.export_to_excel(bundle, output_path)

    def export_to_pillar3(
        self,
        response: CalculationResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export results as Pillar III public disclosure templates."""
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        generator = Pillar3Generator()
        bundle = generator.generate(response)
        return generator.export_to_excel(bundle, output_path)

    # -- reconciliation -----------------------------------------------------

    def export_reconciliation_to_csv(
        self,
        response: ReconciliationResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each reconciliation frame to its own CSV file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _reconciliation_frames(response):
            path = output_dir / f"reconciliation_{name}.csv"
            _csv_safe(df).write_csv(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_reconciliation_to_excel(
        self,
        response: ReconciliationResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export the reconciliation to a multi-sheet Excel workbook.

        Sheets: By Component, Totals Tie-Out, Class Allocation, Class Alloc by Method,
        Reconciliation, Breaks, By Class, By Approach, Errors. Requires xlsxwriter.
        Empty frames are skipped, so the by-method sheet is absent when the ``approach``
        component is unmapped.

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed.
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        import xlsxwriter as xw

        # Friendly sheet titles in report order (headline -> forensic).
        sheet_titles = {
            "summary_by_component": "By Component",
            "totals_tie_out": "Totals Tie-Out",
            "class_allocation": "Class Allocation",
            "class_allocation_by_method": "Class Alloc by Method",
            "summary_by_bucket": "By Bucket",
            "summary_by_exposure_class": "By Class",
            "summary_by_approach": "By Approach",
            "breaks_detail": "Breaks",
            "component_reconciliation": "Reconciliation",
        }
        total_rows = 0
        workbook = xw.Workbook(str(output_path))
        try:
            for name, df in _reconciliation_frames(response):
                if len(df) == 0:
                    continue
                df.write_excel(
                    workbook=workbook,
                    worksheet=sheet_titles.get(name, name)[:31],
                    autofit=True,
                )
                total_rows += len(df)
            errors_df = _reconciliation_errors_frame(response)
            if len(errors_df) > 0:
                errors_df.write_excel(workbook=workbook, worksheet="Errors", autofit=True)
        finally:
            workbook.close()
        return ExportResult(format="excel", files=[output_path], row_count=total_rows)

    # -- comparison ---------------------------------------------------------

    def export_comparison_to_csv(
        self,
        response: ComparisonExportResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each comparison frame to its own CSV file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _comparison_frames(response):
            path = output_dir / f"comparison_{name}.csv"
            _csv_safe(df).write_csv(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="csv", files=files, row_count=total_rows)

    def export_comparison_to_parquet(
        self,
        response: ComparisonExportResponse,
        output_dir: Path,
    ) -> ExportResult:
        """Export each comparison frame to its own Parquet file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        total_rows = 0
        for name, df in _comparison_frames(response):
            path = output_dir / f"comparison_{name}.parquet"
            df.write_parquet(path)
            files.append(path)
            total_rows += len(df)
        return ExportResult(format="parquet", files=files, row_count=total_rows)

    def export_comparison_to_excel(
        self,
        response: ComparisonExportResponse,
        output_path: Path,
    ) -> ExportResult:
        """Export the comparison to a multi-sheet Excel workbook.

        Sheets: Executive Summary, By Class, By Approach, Capital Impact Waterfall,
        Exposure Deltas, Driver Attribution, Errors. Requires xlsxwriter.

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed.
        """
        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "Excel export requires 'xlsxwriter'. Install it with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        import xlsxwriter as xw

        # Friendly sheet titles in report order (headline -> per-exposure detail).
        sheet_titles = {
            "executive_summary": "Executive Summary",
            "summary_by_class": "By Class",
            "summary_by_approach": "By Approach",
            "waterfall": "Capital Impact Waterfall",
            "exposure_deltas": "Exposure Deltas",
            "exposure_attribution": "Driver Attribution",
        }
        total_rows = 0
        workbook = xw.Workbook(str(output_path))
        try:
            for name, df in _comparison_frames(response):
                if len(df) == 0:
                    continue
                df.write_excel(
                    workbook=workbook,
                    worksheet=sheet_titles.get(name, name)[:31],
                    autofit=True,
                )
                total_rows += len(df)
            errors_df = _comparison_errors_frame(response)
            if len(errors_df) > 0:
                errors_df.write_excel(workbook=workbook, worksheet="Errors", autofit=True)
        finally:
            workbook.close()
        return ExportResult(format="excel", files=[output_path], row_count=total_rows)


# =============================================================================
# CSV helpers
# =============================================================================


def _csv_safe(df: pl.DataFrame) -> pl.DataFrame:
    """Return *df* with any nested columns JSON-encoded so CSV can represent them.

    CSV has no nested types, so a List/Array/Struct column makes ``write_csv``
    raise ``ComputeError`` and leave a blank file. The results frame carries a few
    such columns (e.g. ``ancestor_facilities``, ``securitisation_pool_allocations``,
    ``addon_by_asset_class``); each is replaced by its JSON string so the data is
    preserved for downstream tools. Flat frames are returned unchanged.

    The per-row encode only touches the handful of nested columns; ``map_elements``
    is the one encoder uniform across List/Array/Struct in this Polars version.
    """
    nested = [n for n, t in df.schema.items() if t.base_type() in (pl.List, pl.Array, pl.Struct)]
    if not nested:
        return df
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pl.exceptions.PolarsInefficientMapWarning)
        return df.with_columns(
            pl.col(c).map_elements(_json_encode_value, return_dtype=pl.String).alias(c)
            for c in nested
        )


def _json_encode_value(value: object) -> str | None:
    """JSON-encode one nested cell: ``None`` stays null; a Series becomes a list first."""
    if value is None:
        return None
    if isinstance(value, pl.Series):
        value = value.to_list()
    return json.dumps(value, default=str)


# =============================================================================
# Reconciliation export helpers
# =============================================================================


def _reconciliation_frames(
    response: ReconciliationResponse,
) -> list[tuple[str, pl.DataFrame]]:
    """Collect the reconciliation bundle frames in report order (headline first).

    Reads through the response's *memoised* ``collect_*`` accessors rather than
    collecting the raw lazy bundle frames directly. The bundle frames are lazy
    views that re-scan the run's ``last_results.parquet`` on every ``.collect()``;
    reusing the cached eager snapshot (already warmed for the report/explorer) both
    avoids re-executing the reconcile join per export and keeps the export off the
    fresh-disk-re-scan path that can raise "File out of specification: The page
    header reported the wrong page size" on a torn / mis-written results parquet.
    """
    return [
        ("summary_by_component", response.collect_summary_by_component()),
        ("totals_tie_out", response.collect_totals_tie_out()),
        ("class_allocation", response.collect_class_allocation()),
        ("class_allocation_by_method", response.collect_class_allocation_by_method()),
        ("summary_by_bucket", response.collect_summary_by_bucket()),
        ("summary_by_exposure_class", response.collect_summary_by_exposure_class()),
        ("summary_by_approach", response.collect_summary_by_approach()),
        ("breaks_detail", response.collect_breaks_detail()),
        ("component_reconciliation", response.collect_component_reconciliation()),
    ]


def _reconciliation_errors_frame(response: ReconciliationResponse) -> pl.DataFrame:
    """Build a small DataFrame of the reconciliation warnings for the report."""
    return pl.DataFrame(
        {
            "code": [e.code for e in response.errors],
            "severity": [e.severity for e in response.errors],
            "message": [e.message for e in response.errors],
        }
    )


# =============================================================================
# Comparison export helpers
# =============================================================================


def _comparison_frames(
    response: ComparisonExportResponse,
) -> list[tuple[str, pl.DataFrame]]:
    """The comparison export frames in report order (headline first)."""
    return list(response.frames.items())


def _comparison_errors_frame(response: ComparisonExportResponse) -> pl.DataFrame:
    """Build a small DataFrame of the comparison warnings for the report."""
    return pl.DataFrame(
        {
            "code": [e.code for e in response.errors],
            "severity": [e.severity for e in response.errors],
            "message": [e.message for e in response.errors],
        }
    )
