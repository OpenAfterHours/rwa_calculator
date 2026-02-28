"""
API request and response models for RWA Calculator.

RWAService uses these models for clean interface contracts:
- CalculationRequest: Input parameters for RWA calculation
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
from typing import Literal

import polars as pl

# =============================================================================
# Request Models
# =============================================================================


@dataclass(frozen=True)
class CalculationRequest:
    """
    Request model for RWA calculation.

    Encapsulates all parameters needed to run a calculation,
    providing a clean API surface for callers.

    Attributes:
        data_path: Path to directory containing input data files
        framework: Regulatory framework ("CRR" or "BASEL_3_1")
        reporting_date: As-of date for the calculation
        base_currency: Currency for reporting (default GBP)
        irb_approach: IRB approach selection
            - "sa_only": Standardised only, no IRB
            - "firb": Foundation IRB where permitted
            - "airb": Advanced IRB where permitted
            - "full_irb": Both FIRB and AIRB permitted (AIRB preferred)
        data_format: Format of input files ("parquet" or "csv")
        eur_gbp_rate: EUR/GBP exchange rate for threshold conversion
    """

    data_path: str | Path
    framework: Literal["CRR", "BASEL_3_1"]
    reporting_date: date
    base_currency: str = "GBP"
    irb_approach: (
        Literal["sa_only", "firb", "airb", "full_irb", "retail_airb_corporate_firb"] | None
    ) = None
    data_format: Literal["parquet", "csv"] = "parquet"
    eur_gbp_rate: Decimal = field(default_factory=lambda: Decimal("0.8732"))

    @property
    def path(self) -> Path:
        """Get data_path as Path object."""
        return Path(self.data_path)


@dataclass(frozen=True)
class ValidationRequest:
    """
    Request model for data path validation.

    Used to check if a data directory contains the required files
    before running a calculation.

    Attributes:
        data_path: Path to directory to validate
        data_format: Expected format of files ("parquet" or "csv")
    """

    data_path: str | Path
    data_format: Literal["parquet", "csv"] = "parquet"

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
        return self.scan_results().collect()

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
    """

    valid: bool
    data_path: str
    files_found: list[str] = field(default_factory=list)
    files_missing: list[str] = field(default_factory=list)
    errors: list[APIError] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        """Count of missing files."""
        return len(self.files_missing)

    @property
    def found_count(self) -> int:
        """Count of found files."""
        return len(self.files_found)
