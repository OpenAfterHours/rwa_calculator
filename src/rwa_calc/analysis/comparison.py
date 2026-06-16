"""
Dual-Framework Comparison, Capital Impact Analysis, and Transitional Schedule Runners.

Pipeline position:
    Wraps PipelineOrchestrator -> produces ComparisonBundle / CapitalImpactBundle /
    TransitionalScheduleBundle

Key responsibilities:
- Run the same portfolio through both CRR and Basel 3.1 pipelines (M3.1)
- Join per-exposure results on exposure_reference to compute deltas
- Generate summary views by exposure class and approach
- Decompose RWA deltas into attributable regulatory drivers (M3.2)
- Model the transitional output floor schedule across 2027-2032 (M3.3)
- Accumulate errors from all pipeline runs

Why: During the Basel 3.1 transition (PRA PS1/26, effective 1 Jan 2027),
firms must quantify the capital impact of moving from CRR to Basel 3.1.
The output floor phases in from 50% (2027) to 72.5% (2032+), so firms need
year-by-year modelling to plan for the increasing floor bite.

References:
- PRA PS1/26 Ch.12: Output floor transitional period
- CRR Art. 92: Own funds requirements (capital ratios)
- CRR Art. 501/501a: SME and infrastructure supporting factors

Usage:
    from rwa_calc.analysis.comparison import (
        CapitalImpactAnalyzer, DualFrameworkRunner, TransitionalScheduleRunner,
    )

    # M3.1: Side-by-side comparison
    runner = DualFrameworkRunner()
    comparison = runner.compare(raw_data, crr_config, b31_config)

    # M3.2: Capital impact analysis
    analyzer = CapitalImpactAnalyzer()
    impact = analyzer.analyze(comparison)

    # M3.3: Transitional floor schedule modelling
    schedule_runner = TransitionalScheduleRunner()
    schedule = schedule_runner.run(raw_data, permission_mode)
    timeline_df = schedule.timeline.collect()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.analysis.attribution import AttributionResult, get_attributor, register_attributor
from rwa_calc.contracts.bundles import (
    CapitalImpactBundle,
    ComparisonBundle,
    TransitionalScheduleBundle,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)

# Columns to select from each framework's results for the comparison join
_COMPARISON_COLUMNS = [
    "exposure_reference",
    "exposure_class",
    "approach_applied",
    "ead_final",
    "risk_weight",
    "rwa_final",
]

# Optional columns to include if available
_OPTIONAL_COLUMNS = [
    "el_shortfall",
    "el_excess",
    "expected_loss",
    "sa_rwa",
    "supporting_factor",
]


@dataclass(frozen=True)
class RunSpec:
    """One labelled run in a comparison.

    Attributes:
        config: The per-run configuration (regime, elections, reporting date).
        label: Column-suffix + display name for this run (e.g. "crr", "b31",
            "baseline", "amended"). Must be distinct from the other run's label.
        rulepack: Optional resolved-rulepack override (an amendment or election
            overlay built via ``RulepackV0.from_resolved`` /
            ``ResolvedRulepack.with_overrides``). When None, the pipeline resolves
            the pack from ``config`` as usual.
    """

    config: CalculationConfig
    label: str
    rulepack: RulepackV0 | None = None


class DualFrameworkRunner:
    """
    Run the same portfolio through CRR and Basel 3.1 pipelines and compare.

    Uses two separate PipelineOrchestrator instances (one per framework) so
    each run is driven by its own ``CalculationConfig``. CRM components no
    longer carry constructor regime-state — ``CRMProcessor`` reads the framework
    per-method from the effective config — so the split is now purely a matter
    of running each config end-to-end rather than a caching workaround.

    The comparison join is on exposure_reference, producing per-exposure
    delta columns: delta_rwa, delta_risk_weight, delta_ead, delta_pct.
    """

    def compare(
        self,
        data: RawDataBundle,
        baseline: RunSpec | CalculationConfig,
        variant: RunSpec | CalculationConfig,
    ) -> ComparisonBundle:
        """
        Run two labelled configurations on the same data and compare.

        ``baseline`` and ``variant`` may each be a bare ``CalculationConfig`` (its
        ``regime_id`` becomes the label) or a ``RunSpec`` carrying an explicit
        label and optional rulepack overlay. The classic CRR-vs-Basel-3.1
        comparison is ``compare(data, crr_config, b31_config)``; same-regime
        pairings (election-vs-election, regime-vs-amended) pass ``RunSpec`` with
        distinct labels and, optionally, a ``rulepack`` overlay.

        Args:
            data: Pre-loaded raw data bundle (shared between the two runs)
            baseline: The baseline run (config or RunSpec)
            variant: The variant run (config or RunSpec)

        Returns:
            ComparisonBundle with per-exposure deltas and summaries
            (delta = variant - baseline)

        Raises:
            ValueError: If the two runs resolve to the same / an empty label
        """
        base = _as_run_spec(baseline)
        var = _as_run_spec(variant)
        _validate_run_specs(base, var)

        logger.info("Running baseline pipeline (%s)...", base.label)
        baseline_results = PipelineOrchestrator().run_with_data(
            data, base.config, rulepack=base.rulepack
        )

        logger.info("Running variant pipeline (%s)...", var.label)
        variant_results = PipelineOrchestrator().run_with_data(
            data, var.config, rulepack=var.rulepack
        )

        logger.info("Computing exposure-level deltas...")
        exposure_deltas = _compute_exposure_deltas(
            baseline_results, variant_results, base.label, var.label
        )

        logger.info("Generating summary by exposure class...")
        summary_by_class = _compute_summary_by_class(exposure_deltas, base.label, var.label)

        logger.info("Generating summary by approach...")
        summary_by_approach = _compute_summary_by_approach(exposure_deltas, base.label, var.label)

        errors = list(baseline_results.errors) + list(variant_results.errors)

        return ComparisonBundle(
            baseline_results=baseline_results,
            variant_results=variant_results,
            exposure_deltas=exposure_deltas,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            baseline_label=base.label,
            variant_label=var.label,
            errors=errors,
        )


# =============================================================================
# Capital Impact Analysis (M3.2)
# =============================================================================

# IRB approach values used by the aggregator — "foundation_irb" and "advanced_irb"
# from ApproachType enum, plus "FIRB" from aggregator fallback
_IRB_APPROACHES = ["foundation_irb", "advanced_irb", "FIRB"]

# CRR scaling factor for IRB RWA (CRR Art. 153(1)). The Decimal value is the
# canonical regulatory constant in the rulepack; comparison math runs in float
# space, so it's resolved and converted once at import time.
_CRR_SCALING_FACTOR: float = float(resolve("crr", date(2026, 1, 1)).scalar("irb_scaling_factor"))

# Attribution driver labels for the portfolio waterfall
_DRIVER_SCALING = "Scaling factor removal (1.06x)"
_DRIVER_SUPPORTING = "Supporting factor removal (SME/infrastructure)"
_DRIVER_FLOOR = "Output floor impact"
_DRIVER_METHODOLOGY = "Methodology & parameter changes"


class CapitalImpactAnalyzer:
    """
    Decompose the CRR vs Basel 3.1 RWA delta into regulatory drivers (M3.2).

    Takes a pre-computed ComparisonBundle (from DualFrameworkRunner) and produces
    a CapitalImpactBundle with per-exposure driver attribution and portfolio-level
    waterfall.

    Waterfall methodology (sequential, additive):
      CRR RWA
        → Remove 1.06x scaling factor (IRB only)
        → Remove supporting factors (SME/infrastructure)
        → Apply B31 methodology changes (PD/LGD floors, SA risk weights)
        → Apply output floor (IRB only)
      = B31 RWA

    The sum of all four drivers equals the total delta_rwa per exposure.

    Why: Stakeholders need to understand WHY capital requirements change,
    not just by how much. Attribution enables targeted capital planning,
    business-line communication, and regulatory dialogue about which
    Basel 3.1 changes drive the most impact for a given portfolio.

    Usage:
        comparison = DualFrameworkRunner().compare(data, crr_cfg, b31_cfg)
        impact = CapitalImpactAnalyzer().analyze(comparison)
        waterfall_df = impact.portfolio_waterfall.collect()
    """

    def analyze(self, comparison: ComparisonBundle) -> CapitalImpactBundle:
        """
        Decompose comparison deltas into driver-level attribution.

        Args:
            comparison: Pre-computed dual-framework comparison bundle

        Returns:
            CapitalImpactBundle with per-exposure and portfolio attribution
        """
        logger.info("Computing capital impact attribution (M3.2)...")

        # Dispatch to the registered delta-attributor for this run pairing; the
        # CRR->B31 4-driver waterfall is registered under ('crr', 'b31'), and any
        # other pairing falls back to the neutral delta-only attributor.
        result = get_attributor(comparison.baseline_label, comparison.variant_label)(comparison)

        return CapitalImpactBundle(
            exposure_attribution=result.exposure_attribution,
            portfolio_waterfall=result.portfolio_waterfall,
            summary_by_class=result.summary_by_class,
            summary_by_approach=result.summary_by_approach,
            errors=list(comparison.errors),
        )


# =============================================================================
# Transitional Floor Schedule (M3.3)
# =============================================================================

# PRA PS1/26 transitional dates: 1 January of each year
_TRANSITIONAL_REPORTING_DATES = [
    date(2027, 1, 1),  # Year 1: 60% from 1 January (PRA PS1/26 Art. 92(5))
    date(2028, 1, 1),  # Year 2: 65% from 1 January
    date(2029, 1, 1),  # Year 3: 70% from 1 January
    date(2030, 1, 1),  # Year 4: 72.5% from 1 January (steady-state, Art. 92(2A))
]


class TransitionalScheduleRunner:
    """
    Model the output floor phase-in across 2027-2030.

    Runs the same portfolio through the Basel 3.1 pipeline for each
    transitional year, collecting floor impact metrics to produce a
    year-by-year timeline. This enables capital planning for the
    increasing floor bite.

    Why: PRA PS1/26 Art. 92(5) phases in the output floor (60% in 2027
    to 72.5% in 2030+). A portfolio that is not floor-constrained in 2027
    may become floor-constrained as the percentage rises. Modelling this
    trajectory is essential for forward-looking capital management.

    Usage:
        from rwa_calc.analysis.comparison import TransitionalScheduleRunner

        runner = TransitionalScheduleRunner()
        schedule = runner.run(raw_data, permission_mode)
        timeline_df = schedule.timeline.collect()
    """

    def run(
        self,
        data: RawDataBundle,
        permission_mode: PermissionMode = PermissionMode.IRB,
        reporting_dates: list[date] | None = None,
    ) -> TransitionalScheduleBundle:
        """
        Run the B31 pipeline for each transitional year and produce timeline.

        Args:
            data: Pre-loaded raw data bundle (shared across all years)
            permission_mode: STANDARDISED (all SA) or IRB (model permissions drive routing)
            reporting_dates: Optional custom reporting dates (default: 2027-2030, 1 Jan)

        Returns:
            TransitionalScheduleBundle with year-by-year floor impact timeline
        """
        from rwa_calc.contracts.config import CalculationConfig

        dates = reporting_dates or _TRANSITIONAL_REPORTING_DATES
        yearly_results: dict[int, AggregatedResultBundle] = {}
        timeline_rows: list[dict] = []
        all_errors: list = []

        for reporting_date in dates:
            year = reporting_date.year
            logger.info(
                "Running transitional schedule for %d (floor date %s)...", year, reporting_date
            )

            config = CalculationConfig.basel_3_1(
                reporting_date=reporting_date,
                permission_mode=permission_mode,
            )

            pipeline = PipelineOrchestrator()
            result = pipeline.run_with_data(data, config)
            yearly_results[year] = result
            all_errors.extend(result.errors)

            floor_pct = float(config.get_output_floor_percentage())
            row = _extract_floor_metrics(result, reporting_date, floor_pct)
            timeline_rows.append(row)

        timeline = _build_timeline_lazyframe(timeline_rows)

        return TransitionalScheduleBundle(
            timeline=timeline,
            yearly_results=yearly_results,
            errors=all_errors,
        )


def _extract_floor_metrics(
    result: AggregatedResultBundle,
    reporting_date: date,
    floor_pct: float,
) -> dict:
    """Extract floor impact summary metrics from a single pipeline run.

    Collects the floor_impact LazyFrame (if present) and computes
    aggregate metrics for the timeline row.
    """
    year = reporting_date.year
    metrics: dict = {
        "reporting_date": reporting_date,
        "year": year,
        "floor_percentage": floor_pct,
        "total_rwa_pre_floor": 0.0,
        "total_rwa_post_floor": 0.0,
        "total_floor_impact": 0.0,
        "floor_binding_count": 0,
        "total_irb_exposure_count": 0,
        "total_ead": 0.0,
        "total_sa_rwa": 0.0,
    }

    # Get total RWA from summary_by_approach (covers all approaches)
    if result.summary_by_approach is not None:
        try:
            approach_df: pl.DataFrame = result.summary_by_approach.collect()
            if "total_rwa" in approach_df.columns:
                metrics["total_rwa_post_floor"] = approach_df["total_rwa"].sum()
            if "total_ead" in approach_df.columns:
                metrics["total_ead"] = approach_df["total_ead"].sum()
        except Exception:
            logger.warning("Failed to collect summary_by_approach for year %d", year)

    # Get floor-specific metrics from floor_impact
    if result.floor_impact is not None:
        try:
            floor_df: pl.DataFrame = result.floor_impact.collect()
            if floor_df.height > 0:
                metrics["total_irb_exposure_count"] = floor_df.height
                if "rwa_pre_floor" in floor_df.columns:
                    metrics["total_rwa_pre_floor"] = floor_df["rwa_pre_floor"].sum()
                if "floor_impact_rwa" in floor_df.columns:
                    metrics["total_floor_impact"] = floor_df["floor_impact_rwa"].sum()
                if "is_floor_binding" in floor_df.columns:
                    metrics["floor_binding_count"] = int(floor_df["is_floor_binding"].sum())
                if "floor_rwa" in floor_df.columns:
                    metrics["total_sa_rwa"] = floor_df["floor_rwa"].sum() / max(floor_pct, 1e-10)
        except Exception:
            logger.warning("Failed to collect floor_impact for year %d", year)

    return metrics


def _build_timeline_lazyframe(rows: list[dict]) -> pl.LazyFrame:
    """Build the timeline LazyFrame from collected metric rows."""
    if not rows:
        return pl.LazyFrame(
            {
                "reporting_date": pl.Series([], dtype=pl.Date),
                "year": pl.Series([], dtype=pl.Int32),
                "floor_percentage": pl.Series([], dtype=pl.Float64),
                "total_rwa_pre_floor": pl.Series([], dtype=pl.Float64),
                "total_rwa_post_floor": pl.Series([], dtype=pl.Float64),
                "total_floor_impact": pl.Series([], dtype=pl.Float64),
                "floor_binding_count": pl.Series([], dtype=pl.UInt32),
                "total_irb_exposure_count": pl.Series([], dtype=pl.UInt32),
                "total_ead": pl.Series([], dtype=pl.Float64),
                "total_sa_rwa": pl.Series([], dtype=pl.Float64),
            }
        )

    return pl.DataFrame(
        {
            "reporting_date": [r["reporting_date"] for r in rows],
            "year": [r["year"] for r in rows],
            "floor_percentage": [r["floor_percentage"] for r in rows],
            "total_rwa_pre_floor": [r["total_rwa_pre_floor"] for r in rows],
            "total_rwa_post_floor": [r["total_rwa_post_floor"] for r in rows],
            "total_floor_impact": [r["total_floor_impact"] for r in rows],
            "floor_binding_count": [r["floor_binding_count"] for r in rows],
            "total_irb_exposure_count": [r["total_irb_exposure_count"] for r in rows],
            "total_ead": [r["total_ead"] for r in rows],
            "total_sa_rwa": [r["total_sa_rwa"] for r in rows],
        },
        schema={
            "reporting_date": pl.Date,
            "year": pl.Int32,
            "floor_percentage": pl.Float64,
            "total_rwa_pre_floor": pl.Float64,
            "total_rwa_post_floor": pl.Float64,
            "total_floor_impact": pl.Float64,
            "floor_binding_count": pl.UInt32,
            "total_irb_exposure_count": pl.UInt32,
            "total_ead": pl.Float64,
            "total_sa_rwa": pl.Float64,
        },
    ).lazy()


# =============================================================================
# Private Helpers — Dual-Framework Comparison
# =============================================================================


def _as_run_spec(run: RunSpec | CalculationConfig) -> RunSpec:
    """Coerce a bare config to a RunSpec, defaulting the label to its regime id."""
    if isinstance(run, RunSpec):
        return run
    return RunSpec(config=run, label=run.regime_id)


def _validate_run_specs(baseline: RunSpec, variant: RunSpec) -> None:
    """A labelled two-run needs two non-empty, distinct labels (column suffixes)."""
    if not baseline.label or not variant.label:
        raise ValueError("run labels must be non-empty")
    if baseline.label == variant.label:
        raise ValueError(
            f"baseline and variant labels must differ (both {baseline.label!r}); "
            "pass RunSpec(config, label=...) with distinct labels for same-regime runs"
        )


def _select_result_columns(results: AggregatedResultBundle, suffix: str) -> pl.LazyFrame:
    """Select and rename columns from a framework's results for comparison join.

    Picks the core columns needed for delta computation and renames them
    with a framework suffix (e.g., rwa_final -> rwa_crr or rwa_b31).
    """
    lf = results.results
    schema = lf.collect_schema()

    # Always select exposure_reference as the join key (no suffix)
    select_exprs: list[pl.Expr] = [pl.col("exposure_reference")]

    # exposure_class and approach_applied are shared context (no suffix)
    for col_name in ("exposure_class", "approach_applied"):
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    # Core numeric columns get framework suffix
    for col_name in ("ead_final", "risk_weight", "rwa_final"):
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    # Optional columns if they exist
    for col_name in _OPTIONAL_COLUMNS:
        if col_name in schema.names():
            select_exprs.append(pl.col(col_name).alias(f"{col_name}_{suffix}"))

    return lf.select(select_exprs)


def _compute_exposure_deltas(
    baseline_results: AggregatedResultBundle,
    variant_results: AggregatedResultBundle,
    baseline_suffix: str = "crr",
    variant_suffix: str = "b31",
) -> pl.LazyFrame:
    """Join two runs on exposure_reference and compute deltas.

    Delta convention: positive delta means the variant is higher than the baseline
    (increased capital). delta_pct is the change relative to the baseline
    (delta_rwa / baseline_rwa * 100).
    """
    b = baseline_suffix
    v = variant_suffix
    base_lf = _select_result_columns(baseline_results, b)
    var_lf = _select_result_columns(variant_results, v)

    joined = base_lf.join(var_lf, on="exposure_reference", how="full", coalesce=True)

    # Use the baseline exposure class/approach as the primary context; fall back to variant
    joined = joined.with_columns(
        [
            pl.coalesce(pl.col(f"exposure_class_{b}"), pl.col(f"exposure_class_{v}")).alias(
                "exposure_class"
            ),
            pl.coalesce(pl.col(f"approach_applied_{b}"), pl.col(f"approach_applied_{v}")).alias(
                "approach_applied"
            ),
        ]
    )

    # Compute deltas: variant - baseline (positive = increased capital requirement)
    joined = joined.with_columns(
        [
            (
                pl.col(f"rwa_final_{v}").fill_null(0.0) - pl.col(f"rwa_final_{b}").fill_null(0.0)
            ).alias("delta_rwa"),
            (
                pl.col(f"risk_weight_{v}").fill_null(0.0)
                - pl.col(f"risk_weight_{b}").fill_null(0.0)
            ).alias("delta_risk_weight"),
            (
                pl.col(f"ead_final_{v}").fill_null(0.0) - pl.col(f"ead_final_{b}").fill_null(0.0)
            ).alias("delta_ead"),
        ]
    )

    # Percentage change relative to the baseline
    joined = joined.with_columns(
        pl.when(pl.col(f"rwa_final_{b}").abs() > 1e-10)
        .then(pl.col("delta_rwa") / pl.col(f"rwa_final_{b}") * 100.0)
        .otherwise(
            pl.when(pl.col(f"rwa_final_{v}").abs() > 1e-10)
            .then(pl.lit(float("inf")))
            .otherwise(pl.lit(0.0))
        )
        .alias("delta_rwa_pct")
    )

    return joined


def _compute_summary(
    exposure_deltas: pl.LazyFrame,
    group_col: str,
    baseline_suffix: str,
    variant_suffix: str,
) -> pl.LazyFrame:
    """Aggregate RWA/EAD totals and delta RWA by ``group_col`` (class or approach)."""
    b = baseline_suffix
    v = variant_suffix
    return (
        exposure_deltas.group_by(group_col)
        .agg(
            [
                pl.col(f"rwa_final_{b}").sum().alias(f"total_rwa_{b}"),
                pl.col(f"rwa_final_{v}").sum().alias(f"total_rwa_{v}"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col(f"ead_final_{b}").sum().alias(f"total_ead_{b}"),
                pl.col(f"ead_final_{v}").sum().alias(f"total_ead_{v}"),
                pl.len().alias("exposure_count"),
            ]
        )
        .with_columns(
            pl.when(pl.col(f"total_rwa_{b}").abs() > 1e-10)
            .then(pl.col("total_delta_rwa") / pl.col(f"total_rwa_{b}") * 100.0)
            .otherwise(pl.lit(0.0))
            .alias("delta_rwa_pct")
        )
        .sort(group_col)
    )


def _compute_summary_by_class(
    exposure_deltas: pl.LazyFrame,
    baseline_suffix: str = "crr",
    variant_suffix: str = "b31",
) -> pl.LazyFrame:
    """Aggregate delta RWA by exposure class."""
    return _compute_summary(exposure_deltas, "exposure_class", baseline_suffix, variant_suffix)


def _compute_summary_by_approach(
    exposure_deltas: pl.LazyFrame,
    baseline_suffix: str = "crr",
    variant_suffix: str = "b31",
) -> pl.LazyFrame:
    """Aggregate delta RWA by calculation approach."""
    return _compute_summary(exposure_deltas, "approach_applied", baseline_suffix, variant_suffix)


# =============================================================================
# Private Helpers — Capital Impact Analysis (M3.2)
# =============================================================================

# Attribution driver column names
_ATTRIBUTION_DRIVERS = [
    "scaling_factor_impact",
    "supporting_factor_impact",
    "output_floor_impact",
    "methodology_impact",
]


def _safe_col(schema: pl.Schema, col_name: str, default: float = 0.0) -> pl.Expr:
    """Return col expression if present, otherwise a literal default."""
    if col_name in schema.names():
        return pl.col(col_name).fill_null(default)
    return pl.lit(default).alias(col_name)


def _compute_exposure_attribution(comparison: ComparisonBundle) -> pl.LazyFrame:
    """Compute per-exposure driver attribution from CRR and B31 results.

    Joins CRR and B31 aggregated results on exposure_reference, then
    computes the waterfall attribution for each exposure:

    1. scaling_factor_impact: CRR_rwa_final × (1/1.06 - 1) for IRB, else 0
    2. supporting_factor_impact: decomposed from rwa_pre_factor vs rwa_final
    3. output_floor_impact: from B31 floor_impact data
    4. methodology_impact: residual (delta - scaling - supporting - floor)

    The four drivers sum to delta_rwa for every exposure.
    """
    crr = comparison.baseline_results
    b31 = comparison.variant_results

    # Select columns from CRR results
    crr_schema = crr.results.collect_schema()
    # For rwa_pre_factor: if missing, use rwa_final (no supporting factor applied)
    rwa_pre_factor_expr: pl.Expr
    if "rwa_pre_factor" in crr_schema.names():
        rwa_pre_factor_expr = pl.col("rwa_pre_factor").fill_null(pl.col("rwa_final"))
    else:
        rwa_pre_factor_expr = pl.col("rwa_final")

    crr_cols = [
        pl.col("exposure_reference"),
        pl.col("exposure_class")
        if "exposure_class" in crr_schema.names()
        else pl.lit(None).cast(pl.String).alias("exposure_class"),
        pl.col("approach_applied")
        if "approach_applied" in crr_schema.names()
        else pl.lit(None).cast(pl.String).alias("approach_applied"),
        _safe_col(crr_schema, "rwa_final").alias("rwa_crr"),
        rwa_pre_factor_expr.alias("rwa_pre_factor_crr"),
        _safe_col(crr_schema, "supporting_factor", 1.0).alias("supporting_factor_crr"),
    ]
    crr_lf = crr.results.select(crr_cols)

    # Select columns from B31 results
    b31_schema = b31.results.collect_schema()
    b31_cols = [
        pl.col("exposure_reference"),
        _safe_col(b31_schema, "rwa_final").alias("rwa_b31"),
        _safe_col(b31_schema, "rwa_pre_floor").alias("rwa_pre_floor_b31"),
    ]
    b31_lf = b31.results.select(b31_cols)

    # Join CRR and B31 on exposure_reference (full outer join)
    joined = crr_lf.join(b31_lf, on="exposure_reference", how="full", coalesce=True)

    # Left join B31 floor_impact for floor_impact_rwa
    if b31.floor_impact is not None:
        floor_schema = b31.floor_impact.collect_schema()
        if "floor_impact_rwa" in floor_schema.names():
            floor_lf = b31.floor_impact.select(
                [
                    pl.col("exposure_reference"),
                    pl.col("floor_impact_rwa").alias("b31_floor_impact_rwa"),
                ]
            )
            joined = joined.join(floor_lf, on="exposure_reference", how="left")

    # Fill nulls for robustness (exposures missing from one framework)
    joined = joined.with_columns(
        [
            pl.col("rwa_crr").fill_null(0.0),
            pl.col("rwa_b31").fill_null(0.0),
            pl.col("supporting_factor_crr").fill_null(1.0),
            pl.col("rwa_pre_floor_b31").fill_null(pl.col("rwa_b31")),
        ]
    )
    # rwa_pre_factor_crr: fill null with rwa_crr (means no supporting factor)
    joined = joined.with_columns(
        pl.col("rwa_pre_factor_crr").fill_null(pl.col("rwa_crr")),
    )

    # Ensure b31_floor_impact_rwa column exists
    joined_schema = joined.collect_schema()
    if "b31_floor_impact_rwa" not in joined_schema.names():
        joined = joined.with_columns(pl.lit(0.0).alias("b31_floor_impact_rwa"))
    else:
        joined = joined.with_columns(pl.col("b31_floor_impact_rwa").fill_null(0.0))

    # Compute delta
    joined = joined.with_columns(
        (pl.col("rwa_b31") - pl.col("rwa_crr")).alias("delta_rwa"),
    )

    is_irb = pl.col("approach_applied").is_in(_IRB_APPROACHES)

    # =========================================================================
    # Waterfall Step 1: Scaling factor removal (IRB only)
    #
    # CRR applies 1.06x to IRB K. Removing it reduces RWA.
    # Impact = CRR_rwa_final × (1/1.06 - 1)
    # =========================================================================
    joined = joined.with_columns(
        pl.when(is_irb)
        .then(pl.col("rwa_crr") * (1.0 / _CRR_SCALING_FACTOR - 1.0))
        .otherwise(0.0)
        .alias("scaling_factor_impact"),
    )

    # =========================================================================
    # Waterfall Step 2: Supporting factor removal
    #
    # Both `rwa_pre_factor_crr` and `rwa_crr` (rwa_final) already include the
    # 1.06 IRB scaling multiplier per CRR Art. 153(1), so their difference is
    # already on the post-scaling RWA scale. The same formula applies to SA
    # rows (where the 1.06 multiplier is absent on both sides). No further
    # division by _CRR_SCALING_FACTOR is required.
    # =========================================================================
    joined = joined.with_columns(
        (pl.col("rwa_pre_factor_crr") - pl.col("rwa_crr")).alias("supporting_factor_impact"),
    )

    # =========================================================================
    # Waterfall Step 3: Output floor impact (IRB only)
    #
    # Additional RWA from B31 output floor binding.
    # = floor_impact_rwa from the aggregator.
    # =========================================================================
    joined = joined.with_columns(
        pl.when(is_irb)
        .then(pl.col("b31_floor_impact_rwa"))
        .otherwise(0.0)
        .alias("output_floor_impact"),
    )

    # =========================================================================
    # Waterfall Step 4: Methodology & parameter changes (residual)
    #
    # Everything else: PD/LGD floor changes, SA risk weight table changes,
    # F-IRB supervisory LGD changes, correlation formula changes, etc.
    # Computed as: delta - scaling - supporting - floor
    # This ensures the waterfall is exactly additive.
    # =========================================================================
    joined = joined.with_columns(
        (
            pl.col("delta_rwa")
            - pl.col("scaling_factor_impact")
            - pl.col("supporting_factor_impact")
            - pl.col("output_floor_impact")
        ).alias("methodology_impact"),
    )

    # Select final output columns
    return joined.select(
        [
            "exposure_reference",
            "exposure_class",
            "approach_applied",
            "rwa_crr",
            "rwa_b31",
            "delta_rwa",
            "scaling_factor_impact",
            "supporting_factor_impact",
            "output_floor_impact",
            "methodology_impact",
        ]
    )


def _compute_portfolio_waterfall(attribution: pl.LazyFrame) -> pl.LazyFrame:
    """Build a portfolio-level waterfall from per-exposure attribution.

    Produces a 4-row LazyFrame with one row per driver, showing the
    aggregate impact and cumulative RWA from CRR baseline to B31 total.
    """
    # Aggregate each driver across the whole portfolio. Stays lazy: no eager
    # materialisation here, so the function returns a LazyFrame built entirely
    # from lazy operations (LazyFrame-first convention, P6.21).
    totals = attribution.select(
        [
            pl.col("rwa_crr").sum().alias("total_rwa_crr"),
            pl.col("scaling_factor_impact").sum().alias("total_scaling"),
            pl.col("supporting_factor_impact").sum().alias("total_supporting"),
            pl.col("output_floor_impact").sum().alias("total_floor"),
            pl.col("methodology_impact").sum().alias("total_methodology"),
            pl.col("rwa_b31").sum().alias("total_rwa_b31"),
        ]
    )

    # 4-row literal scaffold of (step, driver) in waterfall order; cross-joined with
    # the single-row totals so per-step impact / cumulative are expressed lazily.
    scaffold = pl.LazyFrame(
        {
            "step": [1, 2, 3, 4],
            "driver": [
                _DRIVER_SCALING,
                _DRIVER_SUPPORTING,
                _DRIVER_METHODOLOGY,
                _DRIVER_FLOOR,
            ],
        },
        schema={"step": pl.Int32, "driver": pl.String},
    )

    impact_rwa = (
        pl.when(pl.col("step") == 1)
        .then(pl.col("total_scaling"))
        .when(pl.col("step") == 2)
        .then(pl.col("total_supporting"))
        .when(pl.col("step") == 3)
        .then(pl.col("total_methodology"))
        .otherwise(pl.col("total_floor"))
    )

    cumulative_rwa = (
        pl.when(pl.col("step") == 1)
        .then(pl.col("total_rwa_crr") + pl.col("total_scaling"))
        .when(pl.col("step") == 2)
        .then(pl.col("total_rwa_crr") + pl.col("total_scaling") + pl.col("total_supporting"))
        .when(pl.col("step") == 3)
        .then(
            pl.col("total_rwa_crr")
            + pl.col("total_scaling")
            + pl.col("total_supporting")
            + pl.col("total_methodology")
        )
        .otherwise(
            pl.col("total_rwa_crr")
            + pl.col("total_scaling")
            + pl.col("total_supporting")
            + pl.col("total_methodology")
            + pl.col("total_floor")
        )
    )

    return scaffold.join(totals, how="cross").select(
        [
            pl.col("step"),
            pl.col("driver"),
            impact_rwa.cast(pl.Float64).alias("impact_rwa"),
            cumulative_rwa.cast(pl.Float64).alias("cumulative_rwa"),
        ]
    )


def _compute_attribution_summary(
    attribution: pl.LazyFrame,
    group_col: str,
) -> pl.LazyFrame:
    """Aggregate driver attribution by a grouping column (class or approach)."""
    return (
        attribution.group_by(group_col)
        .agg(
            [
                pl.col("rwa_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("scaling_factor_impact").sum().alias("total_scaling_factor_impact"),
                pl.col("supporting_factor_impact").sum().alias("total_supporting_factor_impact"),
                pl.col("output_floor_impact").sum().alias("total_output_floor_impact"),
                pl.col("methodology_impact").sum().alias("total_methodology_impact"),
                pl.len().alias("exposure_count"),
            ]
        )
        .sort(group_col)
    )


def _crr_to_b31_attribution(comparison: ComparisonBundle) -> AttributionResult:
    """The CRR->Basel-3.1 four-driver waterfall — the registered ('crr', 'b31') pairing.

    Wraps the per-exposure attribution + portfolio waterfall + per-class/approach
    summaries into one AttributionResult. ``CapitalImpactAnalyzer`` dispatches here
    via the attribution registry when both runs carry the default crr / b31 labels.
    """
    attribution = _compute_exposure_attribution(comparison)
    return AttributionResult(
        exposure_attribution=attribution,
        portfolio_waterfall=_compute_portfolio_waterfall(attribution),
        summary_by_class=_compute_attribution_summary(attribution, "exposure_class"),
        summary_by_approach=_compute_attribution_summary(attribution, "approach_applied"),
    )


register_attributor("crr", "b31", _crr_to_b31_attribution)
