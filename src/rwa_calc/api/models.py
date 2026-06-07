"""
API request and response models for RWA Calculator.

Models for clean interface contracts:
- ValidationRequest: Input for data path validation
- CalculationResponse: Calculation results with summary statistics
- ValidationResponse: Data path validation results

All models are frozen dataclasses following existing project patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.api.export import ExportResult
    from rwa_calc.contracts.bundles import ReconciliationBundle


# =============================================================================
# Request Models
# =============================================================================


@dataclass(frozen=True)
class ValidationRequest:
    """
    Request model for data path validation.

    Used to check if a data directory contains the required files
    before running a calculation.

    Attributes:
        data_path: Path to directory to validate
        data_format: Expected format of files ("parquet" or "csv")
        permission_mode: Calculator permission mode. When "irb", the
            validator additionally requires config/model_permissions to be
            present (P1.147).
    """

    data_path: str | Path
    data_format: Literal["parquet", "csv"] = "parquet"
    permission_mode: Literal["standardised", "irb"] = "standardised"

    @property
    def path(self) -> Path:
        """Get data_path as Path object."""
        return Path(self.data_path)


# =============================================================================
# Response Models - Summary Statistics
# =============================================================================


@dataclass(frozen=True)
class SummaryStatistics:
    """
    Aggregated summary statistics from RWA calculation.

    Provides key metrics for quick overview of results.

    Attributes:
        total_ead: Total Exposure at Default
        total_rwa: Total Risk-Weighted Assets
        exposure_count: Number of exposures processed
        average_risk_weight: Average risk weight (RWA / EAD)
        total_ead_sa: Total EAD from Standardised Approach
        total_ead_irb: Total EAD from IRB approaches
        total_ead_slotting: Total EAD from Slotting approach
        total_rwa_sa: Total RWA from Standardised Approach
        total_rwa_irb: Total RWA from IRB approaches
        total_rwa_slotting: Total RWA from Slotting approach
        floor_applied: Whether output floor was binding
        floor_impact: Additional RWA from output floor
        total_el_shortfall: Total EL shortfall (EL > provisions) for IRB exposures
        total_el_excess: Total EL excess (provisions > EL) for IRB exposures
        t2_credit: EL excess addable to T2 capital (capped at 0.6% of IRB RWA)
    """

    total_ead: Decimal
    total_rwa: Decimal
    exposure_count: int
    average_risk_weight: Decimal
    total_ead_sa: Decimal = field(default_factory=lambda: Decimal("0"))
    total_ead_irb: Decimal = field(default_factory=lambda: Decimal("0"))
    total_ead_slotting: Decimal = field(default_factory=lambda: Decimal("0"))
    total_rwa_sa: Decimal = field(default_factory=lambda: Decimal("0"))
    total_rwa_irb: Decimal = field(default_factory=lambda: Decimal("0"))
    total_rwa_slotting: Decimal = field(default_factory=lambda: Decimal("0"))
    floor_applied: bool = False
    floor_impact: Decimal = field(default_factory=lambda: Decimal("0"))
    total_el_shortfall: Decimal = field(default_factory=lambda: Decimal("0"))
    total_el_excess: Decimal = field(default_factory=lambda: Decimal("0"))
    t2_credit: Decimal = field(default_factory=lambda: Decimal("0"))


# =============================================================================
# Response Models - Errors
# =============================================================================


@dataclass(frozen=True)
class APIError:
    """
    User-friendly error representation for API responses.

    Converts internal CalculationError to a format suitable
    for UI display and logging.

    Attributes:
        code: Error code (e.g., "CRM001")
        message: User-friendly error message
        severity: Error severity ("warning", "error", "critical")
        category: Error category for grouping
        details: Additional context (exposure_reference, field_name, etc.)
    """

    code: str
    message: str
    severity: Literal["warning", "error", "critical"]
    category: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"[{self.code}] {self.severity.upper()}: {self.message}"


# =============================================================================
# Response Models - Performance
# =============================================================================


@dataclass(frozen=True)
class PerformanceMetrics:
    """
    Performance metrics for the calculation run.

    Tracks timing and volume for monitoring and optimization.

    Attributes:
        started_at: Calculation start timestamp
        completed_at: Calculation end timestamp
        duration_seconds: Total calculation time in seconds
        exposure_count: Number of exposures processed
        exposures_per_second: Processing throughput
    """

    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    exposure_count: int

    @property
    def exposures_per_second(self) -> float:
        """Calculate processing throughput."""
        if self.duration_seconds > 0:
            return self.exposure_count / self.duration_seconds
        return 0.0


# =============================================================================
# Response Models - Main Responses
# =============================================================================


@dataclass(frozen=True)
class CalculationResponse:
    """
    Response model for RWA calculation results.

    Contains paths to cached parquet files with lazy scan accessors.
    No data is held in memory — callers scan or collect on demand.

    Attributes:
        success: Whether calculation completed without critical errors
        framework: Framework used for calculation
        reporting_date: As-of date for the calculation
        summary: Aggregated summary statistics
        results_path: Path to cached results parquet file
        summary_by_class_path: Path to class summary parquet (or None)
        summary_by_approach_path: Path to approach summary parquet (or None)
        errors: List of errors/warnings encountered
        performance: Performance metrics for the run
    """

    success: bool
    framework: str
    reporting_date: date
    summary: SummaryStatistics
    results_path: Path
    summary_by_class_path: Path | None = None
    summary_by_approach_path: Path | None = None
    errors: list[APIError] = field(default_factory=list)
    performance: PerformanceMetrics | None = None

    def scan_results(self) -> pl.LazyFrame:
        """Lazy-scan the results parquet file."""
        return pl.scan_parquet(self.results_path)

    def collect_results(self) -> pl.DataFrame:
        """Collect the full results into an eager DataFrame."""
        result: pl.DataFrame = self.scan_results().collect()
        return result

    def scan_summary_by_class(self) -> pl.LazyFrame | None:
        """Lazy-scan the class summary parquet, or None if not available."""
        if self.summary_by_class_path and self.summary_by_class_path.exists():
            return pl.scan_parquet(self.summary_by_class_path)
        return None

    def scan_summary_by_approach(self) -> pl.LazyFrame | None:
        """Lazy-scan the approach summary parquet, or None if not available."""
        if self.summary_by_approach_path and self.summary_by_approach_path.exists():
            return pl.scan_parquet(self.summary_by_approach_path)
        return None

    def to_parquet(self, output_dir: Path) -> ExportResult:
        """
        Export results to Parquet files.

        Args:
            output_dir: Directory to write parquet files into

        Returns:
            ExportResult with list of written files and row count
        """
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_to_parquet(self, output_dir)

    def to_csv(self, output_dir: Path) -> ExportResult:
        """
        Export results to CSV files.

        Args:
            output_dir: Directory to write CSV files into

        Returns:
            ExportResult with list of written files and row count
        """
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_to_csv(self, output_dir)

    def to_excel(self, output_path: Path) -> ExportResult:
        """
        Export results to a multi-sheet Excel workbook.

        Requires xlsxwriter to be installed.

        Args:
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_to_excel(self, output_path)

    def to_corep(self, output_path: Path) -> ExportResult:
        """
        Export results as COREP regulatory reporting templates.

        Generates C 07.00 (SA), C 08.01 (IRB totals), C 08.02
        (IRB PD grades) in a multi-sheet Excel workbook following
        the EBA/PRA COREP template structure.

        Requires xlsxwriter to be installed.

        Args:
            output_path: Path for the COREP .xlsx output file

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_to_corep(self, output_path)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return any(e.severity == "warning" for e in self.errors)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors (not warnings)."""
        return any(e.severity in ("error", "critical") for e in self.errors)

    @property
    def warning_count(self) -> int:
        """Count of warnings."""
        return sum(1 for e in self.errors if e.severity == "warning")

    @property
    def error_count(self) -> int:
        """Count of errors (not warnings)."""
        return sum(1 for e in self.errors if e.severity in ("error", "critical"))


@dataclass(frozen=True)
class ValidationResponse:
    """
    Response model for data path validation.

    Reports whether a data directory is valid and contains
    all required files for calculation.

    Attributes:
        valid: Whether the data path is valid for calculation
        data_path: The validated path
        files_found: List of required files that were found
        files_missing: List of required files that are missing
        errors: List of validation errors
        cached_path: Path to cached/processed Parquet files (if any)
    """

    valid: bool
    data_path: Path | str
    files_found: list[Path] = field(default_factory=list)
    files_missing: list[Path] = field(default_factory=list)
    errors: list[APIError] = field(default_factory=list)
    cached_path: Path | str | None = None

    @property
    def missing_count(self) -> int:
        """Count of missing files."""
        return len(self.files_missing)

    @property
    def found_count(self) -> int:
        """Count of found files."""
        return len(self.files_found)


# =============================================================================
# Response Models - Reconciliation
# =============================================================================


@dataclass(frozen=True)
class ReconciliationResponse:
    """
    Response model for a parallel-run reconciliation (legacy vs this calculator).

    Wraps the engine ``ReconciliationBundle`` (lazy frames) with scan/collect
    accessors and export helpers, mirroring ``CalculationResponse`` ergonomics.
    Reconciliation output is small relative to a full run, so frames are kept lazy
    in memory rather than parquet-cached.

    Attributes:
        success: True when at least one component was reconciled.
        bundle: The underlying reconciliation bundle (lazy frames).
        legacy_file: Path to the legacy output that was reconciled.
        framework: Framework our side was run under (for the report header).
        reporting_date: As-of date of our run.
        errors: Non-fatal reconciliation warnings (REC001-REC004), API-friendly.
    """

    success: bool
    bundle: ReconciliationBundle
    legacy_file: Path
    framework: str | None = None
    reporting_date: date | None = None
    errors: list[APIError] = field(default_factory=list)

    @classmethod
    def from_bundle(
        cls,
        bundle: ReconciliationBundle,
        *,
        legacy_file: Path,
        framework: str | None = None,
        reporting_date: date | None = None,
    ) -> ReconciliationResponse:
        """Build a response from an engine bundle, converting errors to APIError."""
        from rwa_calc.api.errors import convert_errors

        # A real bundle's per-key frame carries columns; the empty bundle does not.
        produced = len(bundle.component_reconciliation.collect_schema().names()) > 0
        critical = any(e.severity.value == "critical" for e in bundle.errors)
        return cls(
            success=produced and not critical,
            bundle=bundle,
            legacy_file=legacy_file,
            framework=framework,
            reporting_date=reporting_date,
            errors=convert_errors(bundle.errors),
        )

    def scan_component_reconciliation(self) -> pl.LazyFrame:
        """Lazy per-key reconciliation (legacy vs ours per component)."""
        return self.bundle.component_reconciliation

    def collect_component_reconciliation(self) -> pl.DataFrame:
        """Collect the per-key reconciliation frame."""
        df: pl.DataFrame = self.bundle.component_reconciliation.collect()
        return df

    def collect_summary_by_component(self) -> pl.DataFrame:
        """Collect the headline per-component summary (bucket counts, break rate)."""
        df: pl.DataFrame = self.bundle.summary_by_component.collect()
        return df

    def collect_summary_by_bucket(self) -> pl.DataFrame:
        """Collect the row-level bucket counts."""
        df: pl.DataFrame = self.bundle.summary_by_bucket.collect()
        return df

    def collect_breaks_detail(self) -> pl.DataFrame:
        """Collect the long-format break worklist (ranked by materiality)."""
        df: pl.DataFrame = self.bundle.breaks_detail.collect()
        return df

    def collect_totals_tie_out(self) -> pl.DataFrame:
        """Collect the per-component portfolio tie-out (sum legacy vs sum ours)."""
        df: pl.DataFrame = self.bundle.totals_tie_out.collect()
        return df

    def to_csv(self, output_dir: Path) -> ExportResult:
        """Export the reconciliation frames to CSV files."""
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_reconciliation_to_csv(self, output_dir)

    def to_excel(self, output_path: Path) -> ExportResult:
        """Export the reconciliation to a multi-sheet Excel workbook."""
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_reconciliation_to_excel(self, output_path)

    @property
    def has_breaks(self) -> bool:
        """True when any row reconciled to a break."""
        if not self.success:
            return False
        breaks: pl.DataFrame = (
            self.bundle.summary_by_bucket.filter(pl.col("row_bucket") == "break")
            .select(pl.col("count").sum())
            .collect()
        )
        return bool(breaks.height and (breaks.item() or 0) > 0)
