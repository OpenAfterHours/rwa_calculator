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
    from rwa_calc.contracts.bundles import (
        CapitalImpactBundle,
        ComparisonBundle,
        OutputFloorSummary,
        ReconciliationBundle,
    )


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
        summary_by_class_method_path: Path to class-by-method summary parquet (or None)
        errors: List of errors/warnings encountered
        performance: Performance metrics for the run
        output_floor_summary: Portfolio-level output floor summary (Basel 3.1
            only; None under CRR or when the floor did not run). Carried
            through from the run's ``AggregatedResultBundle`` so reporting
            callers (Pillar 3 OV1/CMS1 floor rows) never have to re-derive it.
        reporting_entity: The reporting-scope entity_reference this run was
            calculated for (multi-entity submissions); None for an un-scoped run.
        reporting_basis: The consolidation basis of the run, as the string value
            of the ``ReportingBasis`` enum (e.g. "consolidated"); None when unset.
    """

    success: bool
    framework: str
    reporting_date: date
    summary: SummaryStatistics
    results_path: Path
    summary_by_class_path: Path | None = None
    summary_by_approach_path: Path | None = None
    summary_by_class_method_path: Path | None = None
    errors: list[APIError] = field(default_factory=list)
    performance: PerformanceMetrics | None = None
    output_floor_summary: OutputFloorSummary | None = None
    reporting_entity: str | None = None
    reporting_basis: str | None = None

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

    def scan_summary_by_class_method(self) -> pl.LazyFrame | None:
        """Lazy-scan the class-by-method summary parquet, or None if not available."""
        if self.summary_by_class_method_path and self.summary_by_class_method_path.exists():
            return pl.scan_parquet(self.summary_by_class_method_path)
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

    def to_pillar3(self, output_path: Path) -> ExportResult:
        """
        Export results as Pillar III quantitative disclosure templates.

        Generates the credit-risk disclosure suite (OV1; SA CR4/CR5; IRB
        CR6/CR6-A/CR7/CR7-A/CR8/CR9/CR9.1; slotting CR10; output-floor CMS1/CMS2;
        counterparty CCR1/CCR2/CCR3/CCR8) in a multi-sheet Excel workbook, with
        UK-prefixed sheet names under CRR and UKB-prefixed under Basel 3.1.

        Requires xlsxwriter to be installed.

        Args:
            output_path: Path for the Pillar III .xlsx output file

        Returns:
            ExportResult with the written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_to_pillar3(self, output_path)

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
    data_path: Path | str
    files_found: list[Path] = field(default_factory=list)
    files_missing: list[Path] = field(default_factory=list)
    errors: list[APIError] = field(default_factory=list)

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
        calculation: The our-side CalculationResponse this reconciliation was
            built from (embedded run or caller-supplied reuse), so a caller can
            index/register it for later reuse. None on the failure path.
    """

    success: bool
    bundle: ReconciliationBundle
    legacy_file: Path
    framework: str | None = None
    reporting_date: date | None = None
    errors: list[APIError] = field(default_factory=list)
    calculation: CalculationResponse | None = None
    # Per-frame collect cache: the bundle frames are lazy views over one
    # shared reconciliation plan, so a raw ``.collect()`` per accessor call
    # re-executes that plan every time. Accessors collect once via
    # ``_collect_cached`` and reuse the eager DataFrame thereafter.
    _collect_cache: dict[str, pl.DataFrame] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    # Memo for the material-only (zero-gross-exposure removed) summary re-derivation:
    # a single dict-of-frames under the "v" key, computed once from the cached wide
    # per-key frame the first time the UI's "hide zero-gross-exposure rows" toggle is
    # used, then reused for the response's lifetime.
    _material_memo: dict[str, dict[str, pl.DataFrame]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @classmethod
    def from_bundle(
        cls,
        bundle: ReconciliationBundle,
        *,
        legacy_file: Path,
        framework: str | None = None,
        reporting_date: date | None = None,
        calculation: CalculationResponse | None = None,
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
            calculation=calculation,
        )

    def scan_component_reconciliation(self) -> pl.LazyFrame:
        """Lazy per-key reconciliation (legacy vs ours per component)."""
        return self.bundle.component_reconciliation

    def collect_component_reconciliation(self) -> pl.DataFrame:
        """Collect the per-key reconciliation frame."""
        return self._collect_cached("component_reconciliation")

    def collect_summary_by_component(self) -> pl.DataFrame:
        """Collect the headline per-component summary (bucket counts, break rate)."""
        return self._collect_cached("summary_by_component")

    def scan_class_allocation(self) -> pl.LazyFrame:
        """Lazy by-risk-class allocation tie-out (ours vs legacy EAD/RWA)."""
        return self.bundle.class_allocation

    def collect_class_allocation(self) -> pl.DataFrame:
        """Collect the by-risk-class allocation tie-out (ours vs legacy EAD/RWA)."""
        return self._collect_cached("class_allocation")

    def scan_class_allocation_by_method(self) -> pl.LazyFrame:
        """Lazy by-(method, risk-class) allocation tie-out (ours vs legacy EAD/RWA)."""
        return self.bundle.class_allocation_by_method

    def collect_class_allocation_by_method(self) -> pl.DataFrame:
        """Collect the allocation tie-out split by methodology within each risk class.

        Empty unless the ``approach`` component is mapped (the legacy side then has a
        method to split on) — callers fall back to ``collect_class_allocation()``.
        """
        return self._collect_cached("class_allocation_by_method")

    def collect_summary_by_bucket(self) -> pl.DataFrame:
        """Collect the row-level bucket counts."""
        return self._collect_cached("summary_by_bucket")

    def collect_summary_by_exposure_class(self) -> pl.DataFrame:
        """Collect the break summary grouped by our exposure class."""
        return self._collect_cached("summary_by_exposure_class")

    def collect_summary_by_approach(self) -> pl.DataFrame:
        """Collect the break summary grouped by our approach."""
        return self._collect_cached("summary_by_approach")

    def collect_summary_by_class_method(self) -> pl.DataFrame:
        """Collect the break summary grouped by (our exposure class, methodology)."""
        return self._collect_cached("summary_by_class_method")

    def scan_breaks_detail(self) -> pl.LazyFrame:
        """Lazy long-format break worklist (ranked by materiality).

        Lets a caller take a top-N slice (the overview's "biggest breaks") without
        forcing the full worklist into the eager cache.
        """
        return self.bundle.breaks_detail

    def collect_breaks_detail(self) -> pl.DataFrame:
        """Collect the long-format break worklist (ranked by materiality)."""
        return self._collect_cached("breaks_detail")

    def collect_totals_tie_out(self) -> pl.DataFrame:
        """Collect the per-component portfolio tie-out (sum legacy vs sum ours)."""
        return self._collect_cached("totals_tie_out")

    def collect_material_summaries(self) -> dict[str, pl.DataFrame]:
        """Material-only summaries (zero-gross-exposure rows removed), cached once.

        Delegates to ``analysis.reconciliation.material_summaries`` over the cached
        wide per-key frame — reusing the engine's own summary builders so the UI's
        "hide zero-gross-exposure rows" view can never diverge from the all-rows
        summaries. Returns a dict keyed by bundle-frame name (``summary_by_bucket``,
        ``summary_by_component``, the three segment summaries, ``totals_tie_out``);
        empty when the reconciliation produced no comparable components, so callers
        fall back to the all-rows accessors.
        """
        if "v" not in self._material_memo:
            from rwa_calc.analysis.reconciliation import material_summaries

            self._material_memo["v"] = material_summaries(self.collect_component_reconciliation())
        return self._material_memo["v"]

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
            self._collect_cached("summary_by_bucket")
            .filter(pl.col("row_bucket") == "break")
            .select(pl.col("count").sum())
        )
        return bool(breaks.height and (breaks.item() or 0) > 0)

    def _collect_cached(self, name: str) -> pl.DataFrame:
        """Collect ``bundle.<name>`` once and reuse the eager DataFrame.

        The reconciliation frames are lazy views sharing one underlying
        reconciliation plan; collecting a view on every accessor call would
        re-execute that plan each time (the REST reconcile endpoint reads
        six views per request). The cache dict is the standard mutable-cache
        escape hatch on a frozen dataclass — it never leaves this class.
        """
        if name not in self._collect_cache:
            df: pl.DataFrame = getattr(self.bundle, name).collect()
            self._collect_cache[name] = df
        return self._collect_cache[name]


# =============================================================================
# Response Models - Comparison export
# =============================================================================


@dataclass(frozen=True)
class ComparisonExportResponse:
    """
    Export wrapper for a CRR vs Basel 3.1 comparison (the comparison page download).

    Holds the comparison's presentation frames already collected into eager
    DataFrames — the executive-summary headline, the by-class / by-approach delta
    summaries, the capital-impact waterfall, and the per-exposure delta /
    driver-attribution frames. Storing collected frames (not the lazy
    ``ComparisonBundle`` + ``CapitalImpactBundle``) keeps the in-process export
    registry light: an entry is just these frames, not two full pipeline plan
    graphs held alive until the process restarts.

    The summaries and waterfall are tiny (one row per class / approach / driver);
    only the per-exposure frames scale with the portfolio — and those are exactly
    the data a download exists to provide.

    Attributes:
        baseline_label: Label for the baseline run (e.g. "crr").
        variant_label: Label for the variant run (e.g. "b31").
        frames: Ordered name -> DataFrame map, in report order, that the exporter
            writes one file / sheet per entry from.
        errors: Combined, API-friendly warnings from both runs and the analysis.
    """

    baseline_label: str
    variant_label: str
    frames: dict[str, pl.DataFrame]
    errors: list[APIError] = field(default_factory=list)

    @classmethod
    def from_bundles(
        cls,
        comparison: ComparisonBundle,
        impact: CapitalImpactBundle,
        *,
        summary: dict[str, float] | None = None,
        baseline_label: str | None = None,
        variant_label: str | None = None,
    ) -> ComparisonExportResponse:
        """Collect the export frames once from the comparison + impact bundles.

        ``summary`` is the executive-summary headline already computed by the UI
        layer (so this api-layer model never imports ``ui.views``); it becomes a
        one-row ``executive_summary`` frame. Each lazy bundle frame is collected
        exactly once here — the response then holds only eager DataFrames.
        """
        from rwa_calc.api.errors import convert_errors

        exec_frame = pl.DataFrame([summary]) if summary else pl.DataFrame()
        frames: dict[str, pl.DataFrame] = {
            "executive_summary": exec_frame,
            "summary_by_class": comparison.summary_by_class.collect(),
            "summary_by_approach": comparison.summary_by_approach.collect(),
            "waterfall": impact.portfolio_waterfall.collect(),
            "exposure_deltas": comparison.exposure_deltas.collect(),
            "exposure_attribution": impact.exposure_attribution.collect(),
        }
        return cls(
            baseline_label=baseline_label or comparison.baseline_label,
            variant_label=variant_label or comparison.variant_label,
            frames=frames,
            errors=convert_errors([*comparison.errors, *impact.errors]),
        )

    def to_csv(self, output_dir: Path) -> ExportResult:
        """Export the comparison frames to CSV files (one per frame)."""
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_comparison_to_csv(self, output_dir)

    def to_parquet(self, output_dir: Path) -> ExportResult:
        """Export the comparison frames to Parquet files (one per frame)."""
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_comparison_to_parquet(self, output_dir)

    def to_excel(self, output_path: Path) -> ExportResult:
        """Export the comparison to a multi-sheet Excel workbook."""
        from rwa_calc.api.export import ResultExporter

        return ResultExporter().export_comparison_to_excel(self, output_path)
