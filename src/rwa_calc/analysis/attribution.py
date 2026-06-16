"""
Delta-attributor registry for capital-impact analysis (migration Phase 6 S4).

A comparison's RWA delta can be decomposed into named regulatory drivers, but the
decomposition is pairing-specific. The CRR->Basel-3.1 waterfall (1.06 scaling
removal, supporting-factor removal, output floor, methodology residual) is ONE
registered attributor, keyed on the run pairing ``('crr', 'b31')``. Any other
pairing (election-vs-election, regime-vs-amended, or any unregistered pair) falls
back to the neutral delta-only attributor defined here — it reports the total RWA
delta per exposure with no driver decomposition.

The registry is keyed on the comparison's ``(baseline_label, variant_label)``,
which default to the runs' regime ids, so the CRR-vs-Basel-3.1 pairing registers
under ``('crr', 'b31')``. The CRR->B31 attributor itself lives with the rest of
the comparison machinery in ``comparison.py`` and registers itself at import; this
module owns the registry and the regime-agnostic neutral fallback.

Pipeline position:
    DualFrameworkRunner -> ComparisonBundle -> CapitalImpactAnalyzer (dispatches
    via this registry) -> CapitalImpactBundle

References:
- PRA PS1/26 Ch.12; CRR Art. 92, 153(1), 501/501a: the CRR->B31 capital drivers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import ComparisonBundle


@dataclass(frozen=True)
class AttributionResult:
    """One pairing's capital-impact attribution.

    Attributes:
        exposure_attribution: Per-exposure attribution frame (driver columns are
            pairing-specific).
        portfolio_waterfall: Portfolio-level driver waterfall (one row per driver).
        summary_by_class: Driver attribution aggregated by exposure class.
        summary_by_approach: Driver attribution aggregated by calculation approach.
    """

    exposure_attribution: pl.LazyFrame
    portfolio_waterfall: pl.LazyFrame
    summary_by_class: pl.LazyFrame
    summary_by_approach: pl.LazyFrame


Attributor = Callable[["ComparisonBundle"], AttributionResult]

# Registry keyed on (baseline_label, variant_label). Labels default to the runs'
# regime ids, so the CRR-vs-Basel-3.1 pairing is ('crr', 'b31').
_REGISTRY: dict[tuple[str, str], Attributor] = {}


def register_attributor(baseline_label: str, variant_label: str, attributor: Attributor) -> None:
    """Register a delta-attributor for a (baseline_label, variant_label) pairing."""
    _REGISTRY[(baseline_label, variant_label)] = attributor


def get_attributor(baseline_label: str, variant_label: str) -> Attributor:
    """Return the registered attributor for the pairing, or the neutral fallback."""
    return _REGISTRY.get((baseline_label, variant_label), neutral_attribution)


def neutral_attribution(comparison: ComparisonBundle) -> AttributionResult:
    """Regime-agnostic delta-only attribution (fallback for unregistered pairings).

    Reports the total RWA delta per exposure under a single "Total delta" driver —
    no scaling / supporting-factor / floor / methodology decomposition (those are
    CRR->B31 specific). Reads the already-computed ``comparison.exposure_deltas``,
    whose numeric columns carry the run labels as suffixes.
    """
    b = comparison.baseline_label
    v = comparison.variant_label
    attribution = comparison.exposure_deltas.select(
        [
            pl.col("exposure_reference"),
            pl.col("exposure_class"),
            pl.col("approach_applied"),
            pl.col(f"rwa_final_{b}").fill_null(0.0).alias("rwa_baseline"),
            pl.col(f"rwa_final_{v}").fill_null(0.0).alias("rwa_variant"),
            pl.col("delta_rwa"),
        ]
    )
    waterfall = attribution.select(
        [
            pl.col("delta_rwa").sum().alias("_total_delta"),
            pl.col("rwa_variant").sum().alias("_total_variant"),
        ]
    ).select(
        [
            pl.lit(1, dtype=pl.Int32).alias("step"),
            pl.lit("Total delta").alias("driver"),
            pl.col("_total_delta").cast(pl.Float64).alias("impact_rwa"),
            pl.col("_total_variant").cast(pl.Float64).alias("cumulative_rwa"),
        ]
    )
    return AttributionResult(
        exposure_attribution=attribution,
        portfolio_waterfall=waterfall,
        summary_by_class=_neutral_summary(attribution, "exposure_class"),
        summary_by_approach=_neutral_summary(attribution, "approach_applied"),
    )


def _neutral_summary(attribution: pl.LazyFrame, group_col: str) -> pl.LazyFrame:
    """Aggregate the neutral (delta-only) attribution by a grouping column."""
    return (
        attribution.group_by(group_col)
        .agg(
            [
                pl.col("rwa_baseline").sum().alias("total_rwa_baseline"),
                pl.col("rwa_variant").sum().alias("total_rwa_variant"),
                pl.col("delta_rwa").sum().alias("total_delta_rwa"),
                pl.len().alias("exposure_count"),
            ]
        )
        .sort(group_col)
    )
