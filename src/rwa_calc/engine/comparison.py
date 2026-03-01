"""
Dual-Framework Comparison Runner for RWA Calculator.

Pipeline position:
    Wraps PipelineOrchestrator -> produces ComparisonBundle

Key responsibilities:
- Run the same portfolio through both CRR and Basel 3.1 pipelines
- Join per-exposure results on exposure_reference to compute deltas
- Generate summary views by exposure class and approach
- Accumulate errors from both pipeline runs

Why: During the Basel 3.1 transition (PRA PS9/24, effective 1 Jan 2027),
firms must quantify the capital impact of moving from CRR to Basel 3.1.
This module provides the orchestration layer for side-by-side comparison.

References:
- PRA PS9/24 Ch.12: Output floor transitional period
- CRR Art. 92: Own funds requirements (capital ratios)

Usage:
    from rwa_calc.engine.comparison import DualFrameworkRunner

    runner = DualFrameworkRunner()
    comparison = runner.compare(raw_data, crr_config, b31_config)

    # Per-exposure deltas
    deltas_df = comparison.exposure_deltas.collect()

    # Summary by class
    class_impact = comparison.summary_by_class.collect()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import ComparisonBundle
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig

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


class DualFrameworkRunner:
    """
    Run the same portfolio through CRR and Basel 3.1 pipelines and compare.

    Uses two separate PipelineOrchestrator instances (one per framework)
    to avoid CRM processor caching issues — each orchestrator initializes
    its own CRMProcessor with the correct is_basel_3_1 flag.

    The comparison join is on exposure_reference, producing per-exposure
    delta columns: delta_rwa, delta_risk_weight, delta_ead, delta_pct.
    """

    def compare(
        self,
        data: RawDataBundle,
        crr_config: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> ComparisonBundle:
        """
        Run both frameworks on the same data and produce comparison.

        Args:
            data: Pre-loaded raw data bundle (shared between frameworks)
            crr_config: CRR configuration (must have framework=CRR)
            b31_config: Basel 3.1 configuration (must have framework=BASEL_3_1)

        Returns:
            ComparisonBundle with per-exposure deltas and summaries

        Raises:
            ValueError: If configs have wrong framework types
        """
        _validate_configs(crr_config, b31_config)

        logger.info("Running CRR pipeline...")
        crr_pipeline = PipelineOrchestrator()
        crr_results = crr_pipeline.run_with_data(data, crr_config)

        logger.info("Running Basel 3.1 pipeline...")
        b31_pipeline = PipelineOrchestrator()
        b31_results = b31_pipeline.run_with_data(data, b31_config)

        logger.info("Computing exposure-level deltas...")
        exposure_deltas = _compute_exposure_deltas(crr_results, b31_results)

        logger.info("Generating summary by exposure class...")
        summary_by_class = _compute_summary_by_class(exposure_deltas)

        logger.info("Generating summary by approach...")
        summary_by_approach = _compute_summary_by_approach(exposure_deltas)

        errors = list(crr_results.errors) + list(b31_results.errors)

        return ComparisonBundle(
            crr_results=crr_results,
            b31_results=b31_results,
            exposure_deltas=exposure_deltas,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            errors=errors,
        )


# =============================================================================
# Private Helpers
# =============================================================================


def _validate_configs(crr_config: CalculationConfig, b31_config: CalculationConfig) -> None:
    """Validate that configs have correct framework types."""
    if not crr_config.is_crr:
        raise ValueError(f"crr_config must use CRR framework, got {crr_config.framework}")
    if not b31_config.is_basel_3_1:
        raise ValueError(f"b31_config must use Basel 3.1 framework, got {b31_config.framework}")


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
    crr_results: AggregatedResultBundle,
    b31_results: AggregatedResultBundle,
) -> pl.LazyFrame:
    """Join CRR and B31 results on exposure_reference and compute deltas.

    Delta convention: positive delta means B31 is higher than CRR (increased capital).
    delta_pct is the percentage change relative to CRR (delta_rwa / crr_rwa * 100).
    """
    crr_lf = _select_result_columns(crr_results, "crr")
    b31_lf = _select_result_columns(b31_results, "b31")

    joined = crr_lf.join(b31_lf, on="exposure_reference", how="full", coalesce=True)

    # Use CRR exposure class/approach as the primary context; fall back to B31
    joined = joined.with_columns(
        [
            pl.coalesce(pl.col("exposure_class_crr"), pl.col("exposure_class_b31")).alias(
                "exposure_class"
            ),
            pl.coalesce(pl.col("approach_applied_crr"), pl.col("approach_applied_b31")).alias(
                "approach_applied"
            ),
        ]
    )

    # Compute deltas: B31 - CRR (positive = increased capital requirement)
    joined = joined.with_columns(
        [
            (pl.col("rwa_final_b31").fill_null(0.0) - pl.col("rwa_final_crr").fill_null(0.0)).alias(
                "delta_rwa"
            ),
            (
                pl.col("risk_weight_b31").fill_null(0.0) - pl.col("risk_weight_crr").fill_null(0.0)
            ).alias("delta_risk_weight"),
            (pl.col("ead_final_b31").fill_null(0.0) - pl.col("ead_final_crr").fill_null(0.0)).alias(
                "delta_ead"
            ),
        ]
    )

    # Percentage change relative to CRR
    joined = joined.with_columns(
        pl.when(pl.col("rwa_final_crr").abs() > 1e-10)
        .then(pl.col("delta_rwa") / pl.col("rwa_final_crr") * 100.0)
        .otherwise(
            pl.when(pl.col("rwa_final_b31").abs() > 1e-10)
            .then(pl.lit(float("inf")))
            .otherwise(pl.lit(0.0))
        )
        .alias("delta_rwa_pct")
    )

    return joined


def _compute_summary_by_class(exposure_deltas: pl.LazyFrame) -> pl.LazyFrame:
    """Aggregate delta RWA by exposure class."""
    return (
        exposure_deltas.group_by("exposure_class")
        .agg(
            [
                pl.col("rwa_final_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_final_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("ead_final_crr").sum().alias("total_ead_crr"),
                pl.col("ead_final_b31").sum().alias("total_ead_b31"),
                pl.len().alias("exposure_count"),
            ]
        )
        .with_columns(
            pl.when(pl.col("total_rwa_crr").abs() > 1e-10)
            .then(pl.col("total_delta_rwa") / pl.col("total_rwa_crr") * 100.0)
            .otherwise(pl.lit(0.0))
            .alias("delta_rwa_pct")
        )
        .sort("exposure_class")
    )


def _compute_summary_by_approach(exposure_deltas: pl.LazyFrame) -> pl.LazyFrame:
    """Aggregate delta RWA by calculation approach."""
    return (
        exposure_deltas.group_by("approach_applied")
        .agg(
            [
                pl.col("rwa_final_crr").sum().alias("total_rwa_crr"),
                pl.col("rwa_final_b31").sum().alias("total_rwa_b31"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.col("ead_final_crr").sum().alias("total_ead_crr"),
                pl.col("ead_final_b31").sum().alias("total_ead_b31"),
                pl.len().alias("exposure_count"),
            ]
        )
        .with_columns(
            pl.when(pl.col("total_rwa_crr").abs() > 1e-10)
            .then(pl.col("total_delta_rwa") / pl.col("total_rwa_crr") * 100.0)
            .otherwise(pl.lit(0.0))
            .alias("delta_rwa_pct")
        )
        .sort("approach_applied")
    )
