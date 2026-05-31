"""
Collateral link allocation — split one finite collateral item across many beneficiaries.

Pipeline position:
    Classifier -> CRMProcessor [link_allocation -> apply_collateral] -> Calculators

Key responsibilities:
- Expand the optional M:N ``collateral_links`` table into per-beneficiary
  collateral rows, one slice per linked beneficiary.
- Split each finite collateral value across its linked beneficiaries for the
  most beneficial RWA impact: a greedy fill of the highest pre-CRM RWA-density
  beneficiary first (or a firm-supplied ``priority`` override), honouring an
  optional per-link ``max_pledge_amount`` cap, and never over-claiming
  (Σ slices ≤ value) by construction.
- Emit an expanded collateral frame with the same shape as the single-
  beneficiary collateral table, so the existing Art. 231 waterfall in
  ``apply_collateral`` consumes it unchanged.

The split reuses the cumulative-cap trick already used by the waterfall
(``slice_i = min(cum_i, V) - min(prev_i, V)``): within each collateral item the
linked beneficiaries are ranked, their EAD demand is accumulated, and the slice
each absorbs is the increment of the cumulative demand capped at the finite
value ``V``.

References:
- CRR Art. 193/194/207: CRM eligibility and recognition conditions
- CRR Art. 230-231: substitution / sequential allocation of collateral
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from watchfire import cites

from rwa_calc.engine.crm.expressions import beneficiary_level_expr

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)

#: Column on the exposures frame carrying the pre-CRM RWA-density ranking metric
#: (higher = more beneficial to collateralise first). Supplied by the CRM
#: processor's ranking pre-pass; defaults to 0.0 when absent.
RANK_METRIC_COLUMN = "_link_rank_metric"

@dataclass(frozen=True)
class CollateralLinkAllocation:
    """Result of expanding the M:N collateral-links table.

    Attributes:
        collateral: Expanded collateral frame — one row per resolved
            (collateral_reference, beneficiary) slice for linked items, plus the
            unlinked collateral rows passed through unchanged. Same column shape
            as the input collateral table.
        audit: One row per link with the demand, ranking metric, finite value,
            and allocated slice. None when no links were applied.
        errors: Accumulated data-quality errors (never raised).
    """

    collateral: pl.LazyFrame
    audit: pl.LazyFrame | None = None
    errors: list[CalculationError] = field(default_factory=list)


class CollateralLinkAllocator:
    """Split finite collateral values across linked beneficiaries (Art. 230-231).

    Implements ``CollateralLinkAllocatorProtocol``. Pure with respect to the
    exposures frame — it only reads exposures to size and rank beneficiaries and
    returns an expanded collateral frame; the exposures frame is not mutated.
    """

    @cites("CRR Art. 230")
    @cites("CRR Art. 231")
    def allocate_links(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
        collateral_links: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> CollateralLinkAllocation:
        """Expand ``collateral_links`` into per-beneficiary collateral slices.

        Returns the original collateral unchanged when no usable links table is
        supplied (the single-beneficiary path). Never raises.
        """
        if collateral is None or collateral_links is None:
            return CollateralLinkAllocation(collateral=collateral or pl.LazyFrame(), audit=None)

        coll_cols = collateral.collect_schema().names()
        link_cols = set(collateral_links.collect_schema().names())
        required = {"collateral_reference", "beneficiary_type", "beneficiary_reference"}
        if "collateral_reference" not in coll_cols or not required.issubset(link_cols):
            return CollateralLinkAllocation(collateral=collateral, audit=None)

        demand_metric = self._beneficiary_demand_metric(exposures)
        links = self._resolve_links(collateral_links, collateral, demand_metric, link_cols)
        links = self._allocate_slices(links)

        expanded = self._build_expanded_collateral(collateral, links, coll_cols)
        passthrough = collateral.join(
            collateral_links.select(pl.col("collateral_reference").cast(pl.String)).unique(),
            on="collateral_reference",
            how="anti",
        )
        merged = pl.concat([passthrough, expanded], how="vertical_relaxed")

        audit = links.select(
            pl.col("collateral_reference"),
            pl.col("beneficiary_type"),
            pl.col("beneficiary_reference"),
            pl.col("_demand").alias("beneficiary_demand"),
            pl.col("_metric").alias("rank_metric"),
            pl.col("_value").alias("collateral_value"),
            pl.col("_slice").alias("allocated_value"),
        )
        return CollateralLinkAllocation(collateral=merged, audit=audit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _beneficiary_demand_metric(self, exposures: pl.LazyFrame) -> dict[str, pl.LazyFrame]:
        """Per-level (reference -> demand, metric) lookups.

        Direct beneficiaries (exposure/loan/contingent) resolve to a single
        exposure; facility / counterparty beneficiaries pool their children's
        EAD demand and take the EAD-weighted average ranking metric.
        """
        exp_cols = set(exposures.collect_schema().names())
        ead_expr = (
            pl.col("ead_for_crm") if "ead_for_crm" in exp_cols else pl.col("ead_gross")
        ).cast(pl.Float64)
        metric_expr = (
            pl.col(RANK_METRIC_COLUMN) if RANK_METRIC_COLUMN in exp_cols else pl.lit(0.0)
        ).cast(pl.Float64)

        def _opt_ref(col: str) -> pl.Expr:
            return (
                pl.col(col).cast(pl.String) if col in exp_cols else pl.lit(None, dtype=pl.String)
            ).alias(col)

        base = exposures.select(
            pl.col("exposure_reference").cast(pl.String),
            ead_expr.alias("_demand"),
            metric_expr.alias("_metric"),
            _opt_ref("parent_facility_reference"),
            _opt_ref("counterparty_reference"),
        )

        direct = base.select(
            pl.col("exposure_reference").alias("_ref"), "_demand", "_metric"
        )
        facility = self._pool_lookup(base, "parent_facility_reference")
        counterparty = self._pool_lookup(base, "counterparty_reference")
        return {"direct": direct, "facility": facility, "counterparty": counterparty}

    @staticmethod
    def _pool_lookup(base: pl.LazyFrame, key: str) -> pl.LazyFrame:
        """Pooled demand + EAD-weighted metric for facility / counterparty keys."""
        return (
            base.filter(pl.col(key).is_not_null())
            .group_by(key)
            .agg(
                pl.col("_demand").sum().alias("_demand"),
                (pl.col("_metric") * pl.col("_demand")).sum().alias("_wm"),
            )
            .with_columns(
                pl.when(pl.col("_demand") > 0)
                .then(pl.col("_wm") / pl.col("_demand"))
                .otherwise(pl.lit(0.0))
                .alias("_metric")
            )
            .select(pl.col(key).alias("_ref"), "_demand", "_metric")
        )

    def _resolve_links(
        self,
        collateral_links: pl.LazyFrame,
        collateral: pl.LazyFrame,
        demand_metric: dict[str, pl.LazyFrame],
        link_cols: set[str],
    ) -> pl.LazyFrame:
        """Attach demand, ranking metric and finite value to each link row."""
        links = collateral_links.select(
            pl.col("collateral_reference").cast(pl.String),
            pl.col("beneficiary_type").cast(pl.String),
            pl.col("beneficiary_reference").cast(pl.String),
            (
                pl.col("max_pledge_amount").cast(pl.Float64)
                if "max_pledge_amount" in link_cols
                else pl.lit(None, dtype=pl.Float64)
            ).alias("max_pledge_amount"),
            (
                pl.col("priority").cast(pl.Int64)
                if "priority" in link_cols
                else pl.lit(None, dtype=pl.Int64)
            ).alias("priority"),
        ).with_columns(beneficiary_level_expr("beneficiary_type").alias("_level"))

        links = (
            links.join(
                demand_metric["direct"].rename({"_demand": "_d_d", "_metric": "_m_d"}),
                left_on="beneficiary_reference",
                right_on="_ref",
                how="left",
            )
            .join(
                demand_metric["facility"].rename({"_demand": "_d_f", "_metric": "_m_f"}),
                left_on="beneficiary_reference",
                right_on="_ref",
                how="left",
            )
            .join(
                demand_metric["counterparty"].rename({"_demand": "_d_c", "_metric": "_m_c"}),
                left_on="beneficiary_reference",
                right_on="_ref",
                how="left",
            )
        )

        links = links.with_columns(
            pl.when(pl.col("_level") == "facility")
            .then(pl.col("_d_f"))
            .when(pl.col("_level") == "counterparty")
            .then(pl.col("_d_c"))
            .otherwise(pl.col("_d_d"))
            .fill_null(0.0)
            .alias("_demand"),
            pl.when(pl.col("_level") == "facility")
            .then(pl.col("_m_f"))
            .when(pl.col("_level") == "counterparty")
            .then(pl.col("_m_c"))
            .otherwise(pl.col("_m_d"))
            .fill_null(0.0)
            .alias("_metric"),
        )

        value_lookup = collateral.select(
            pl.col("collateral_reference").cast(pl.String),
            self._finite_value_expr(collateral).alias("_value"),
        )
        return links.join(value_lookup, on="collateral_reference", how="left")

    @staticmethod
    def _finite_value_expr(collateral: pl.LazyFrame) -> pl.Expr:
        """The item's finite value: market_value, falling back to nominal_value."""
        cols = set(collateral.collect_schema().names())
        candidates: list[pl.Expr] = []
        if "market_value" in cols:
            candidates.append(pl.col("market_value").cast(pl.Float64))
        if "nominal_value" in cols:
            candidates.append(pl.col("nominal_value").cast(pl.Float64))
        if not candidates:
            return pl.lit(0.0)
        return pl.coalesce(candidates).fill_null(0.0)

    @staticmethod
    def _allocate_slices(links: pl.LazyFrame) -> pl.LazyFrame:
        """Greedy cumulative-cap split within each collateral_reference."""
        links = links.with_columns(
            pl.when(pl.col("max_pledge_amount").is_not_null())
            .then(pl.min_horizontal(pl.col("_demand"), pl.col("max_pledge_amount")))
            .otherwise(pl.col("_demand"))
            .clip(lower_bound=0.0)
            .alias("_demand_eff"),
            # Explicit priorities fill first; links without one (null) rank after,
            # ordered by descending metric, with a deterministic lexical tie-break.
            pl.col("priority").is_null().cast(pl.Int8).alias("_ord_pri_null"),
            pl.col("priority").fill_null(0).alias("_ord_priority"),
            (-pl.col("_metric")).alias("_ord_negmetric"),
        )
        links = links.with_columns(
            pl.col("_demand_eff")
            .cum_sum()
            .over(
                "collateral_reference",
                order_by=[
                    "_ord_pri_null",
                    "_ord_priority",
                    "_ord_negmetric",
                    "beneficiary_type",
                    "beneficiary_reference",
                ],
            )
            .alias("_cum")
        )
        return links.with_columns(
            (
                pl.min_horizontal(pl.col("_cum"), pl.col("_value"))
                - pl.min_horizontal(pl.col("_cum") - pl.col("_demand_eff"), pl.col("_value"))
            )
            .clip(lower_bound=0.0)
            .alias("_slice")
        )

    @staticmethod
    def _build_expanded_collateral(
        collateral: pl.LazyFrame,
        links: pl.LazyFrame,
        coll_cols: list[str],
    ) -> pl.LazyFrame:
        """One collateral row per non-empty slice, in the original column shape."""
        schema = collateral.collect_schema()
        # Columns sourced from the link / slice rather than the collateral row:
        # the slice amount is written to market_value; nominal_value and
        # pledge_percentage are nulled so the sliced value is authoritative.
        override = {
            "beneficiary_type",
            "beneficiary_reference",
            "market_value",
            "nominal_value",
            "pledge_percentage",
        }
        attr_cols = [c for c in coll_cols if c not in override]
        attrs = collateral.select(attr_cols)

        sliced = links.filter(pl.col("_slice") > 1e-9).join(
            attrs, on="collateral_reference", how="left"
        )

        final_exprs: list[pl.Expr] = []
        for col in coll_cols:
            if col in {"beneficiary_type", "beneficiary_reference"}:
                final_exprs.append(pl.col(col))  # from the link row
            elif col == "market_value":
                final_exprs.append(pl.col("_slice").cast(schema[col]).alias("market_value"))
            elif col in {"nominal_value", "pledge_percentage"}:
                final_exprs.append(pl.lit(None).cast(schema[col]).alias(col))
            else:
                final_exprs.append(pl.col(col))
        return sliced.select(final_exprs)
