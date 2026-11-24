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
- Treat a ``collateral_reference`` stated on several collateral rows (a breach
  of the input contract, reported as DQ004 by the input gate) as ONE item: the
  row stating the smallest finite value supplies the value and the attributes,
  so no item is credited more than any single row states, and over the same
  exposure frame THIS module's slices are those a feed stating the item once
  at that value would receive (PS1/26 Art. 193(7)(b), "without any
  double-counting"; review CL-03, P1.444). This module runs only with collateral-link splitting enabled; with
  it disabled the duplicate rows are applied as stated. The repair is local to
  this split: real-estate property attributes (LTV, property type, property
  coverage, the loan split) are read per raw row upstream, in the hierarchy
  stage, and third-party deposits leave the collateral frame before this
  module runs (``processor.py`` Step 3.65), so both are still applied once per
  row even when links name the item (and a duplicated property's per-row loan
  split also changes the exposure frame this module receives).

The split is a JOINT, residual-demand-aware fill across all collateral items
at once: link edges are walked in a single global order (explicit ``priority``
first, then descending beneficiary RWA density, then a most-constrained-item
tie-break) and each edge absorbs ``min(item supply remaining, beneficiary
demand remaining, per-link cap)``, decrementing both residuals. Once a
beneficiary's demand is filled by one item, later items see zero residual
demand there and spill to the next-best beneficiary — so two items linked to
the same facilities no longer both pile onto the highest-RW one. It is a
deterministic greedy heuristic (not a global LP optimum): optimal when
collateral is fungible across the linked beneficiaries and on the
restricted-eligibility case, and it reduces to the legacy single-item
cumulative-cap split when an item links exactly one beneficiary. The per-edge
supply cap preserves the ``Σ slices ≤ V`` guarantee for every item.

References:
- CRR Art. 193/194/207: CRM eligibility and recognition conditions
- CRR Art. 230-231: substitution / sequential allocation of collateral
- PS1/26 Art. 193(7): an item covering several exposures is subdivided into
  portions, each allocated to one exposure without double-counting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.engine.crm.expressions import beneficiary_level_expr
from rwa_calc.engine.kernels.allocation import direct_level_lookup, grouped_level_lookup

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

    collateral: pl.LazyFrame | None
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
            # Absent collateral stays None — never an empty-frame sentinel.
            return CollateralLinkAllocation(collateral=collateral, audit=None)

        coll_cols = collateral.collect_schema().names()
        link_cols = set(collateral_links.collect_schema().names())
        required = {"collateral_reference", "beneficiary_type", "beneficiary_reference"}
        if "collateral_reference" not in coll_cols or not required.issubset(link_cols):
            return CollateralLinkAllocation(collateral=collateral, audit=None)

        items = _one_row_per_item(collateral, self._finite_value_expr(collateral), coll_cols)
        demand_metric = self._beneficiary_demand_metric(exposures)
        links = self._resolve_links(collateral_links, items, demand_metric, link_cols)
        links = self._allocate_slices(links)

        expanded = self._build_expanded_collateral(items, links, coll_cols)
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

        direct = direct_level_lookup(
            base,
            key="exposure_reference",
            out_key="_ref",
            values=[pl.col("_demand"), pl.col("_metric")],
        )
        facility = self._pool_lookup(base, "parent_facility_reference")
        counterparty = self._pool_lookup(base, "counterparty_reference")
        return {"direct": direct, "facility": facility, "counterparty": counterparty}

    @staticmethod
    def _pool_lookup(base: pl.LazyFrame, key: str) -> pl.LazyFrame:
        """Pooled demand + EAD-weighted metric for facility / counterparty keys.

        Kernel-backed grouped level lookup over the non-null-keyed rows; the
        EAD-weighted average metric ratio is link-allocation-specific and
        stays here.
        """
        return (
            grouped_level_lookup(
                base.filter(pl.col(key).is_not_null()),
                key=key,
                out_key="_ref",
                values=[
                    pl.col("_demand").sum().alias("_demand"),
                    (pl.col("_metric") * pl.col("_demand")).sum().alias("_wm"),
                ],
            )
            .with_columns(
                pl.when(pl.col("_demand") > 0)
                .then(pl.col("_wm") / pl.col("_demand"))
                .otherwise(pl.lit(0.0))
                .alias("_metric")
            )
            .select("_ref", "_demand", "_metric")
        )

    def _resolve_links(
        self,
        collateral_links: pl.LazyFrame,
        items: pl.LazyFrame,
        demand_metric: dict[str, pl.LazyFrame],
        link_cols: set[str],
    ) -> pl.LazyFrame:
        """Attach demand, ranking metric and finite value to each link row.

        ``items`` is :func:`_one_row_per_item`'s frame, so the value join adds
        at most one row per link edge.
        """
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

        value_lookup = items.select("collateral_reference", "_value")
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
        """Joint, residual-demand-aware split of finite collateral across links.

        Adds a ``_slice`` column to each link edge: the amount that edge
        absorbs after walking all edges in a single global priority order and
        decrementing BOTH the item's remaining finite value (supply) and the
        beneficiary's remaining demand. See the module docstring for the
        rationale and the heuristic-not-LP caveat.

        A bounded Python walk is used because the two-sided residual (supply
        AND demand) cannot be expressed as a single vectorised cumulative sum.
        The ``.collect()`` here is a one-time pre-pass over the small
        collateral_links edge set — gated upstream by
        ``enable_collateral_link_splitting`` so it never runs on the
        per-exposure hot path — not a pipeline-branch barrier.
        """
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
            # Most-constrained-item tie-break: an item linked to fewer
            # beneficiaries draws first, so supply that can only go to the
            # current beneficiary is not stranded by a more flexible item.
            pl.len().over("collateral_reference").alias("_item_fanout"),
        )
        ordered = links.sort(
            by=[
                "_ord_pri_null",
                "_ord_priority",
                "_ord_negmetric",
                "beneficiary_type",
                "beneficiary_reference",
                "_item_fanout",
                "collateral_reference",
            ]
        ).collect()  # small link-set pre-pass; not a pipeline barrier

        slices = _residual_fill(
            ordered.get_column("collateral_reference").to_list(),
            ordered.get_column("beneficiary_type").to_list(),
            ordered.get_column("beneficiary_reference").to_list(),
            ordered.get_column("_value").to_list(),
            ordered.get_column("_demand").to_list(),
            ordered.get_column("_demand_eff").to_list(),
        )
        return ordered.with_columns(pl.Series("_slice", slices, dtype=pl.Float64)).lazy()

    @staticmethod
    def _build_expanded_collateral(
        items: pl.LazyFrame,
        links: pl.LazyFrame,
        coll_cols: list[str],
    ) -> pl.LazyFrame:
        """One collateral row per non-empty slice, in the original column shape.

        Attributes come from :func:`_one_row_per_item`'s frame, so each slice
        joins exactly one collateral row.
        """
        schema = items.collect_schema()
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
        attrs = items.select(attr_cols)

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


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


@cites("PS1/26, paragraph 193")
def _one_row_per_item(collateral: pl.LazyFrame, value: pl.Expr, columns: list[str]) -> pl.LazyFrame:
    """One row per non-null ``collateral_reference``, carrying its finite ``_value``.

    A reference names one item, so a reference on several rows is the same
    item supplied twice (DQ004 at the input gate). Keyed on the reference
    alone, the value and attribute joins fanned out on it — an item stated
    twice at 60 reached its beneficiary as two slices of 60 — the value
    seeded for the split depended on which duplicate sorted first, and the
    doubled edges inflated the item's ``_item_fanout``, so at a beneficiary it
    shares with another item it drew in a different order than it would from a
    well-formed feed. Over the same exposure frame, one row per item restores
    this split's well-formed slices exactly, which can move RWA either way against the duplicated feed's old
    result: lower where the fan-out had pushed a more useful item's supply onto
    the wrong beneficiary. It does not reach what is read before this module
    (real-estate property attributes in the hierarchy stage, third-party
    deposits split out at ``processor.py`` Step 3.65): those still see every
    duplicate row.

    The surviving row is the one stating the SMALLEST finite ``value`` (ties:
    beneficiary, then input order), and it supplies the attributes too, so the
    slice is valued and haircut as one stated row. The minimum is the only
    choice that credits no item more than any of its rows states — not the
    keep-largest rule of the guarantee pool
    (``protection_value.py::attach_shared_cap``), which can lower RWA here.
    PS1/26 Art. 193(7)(b): each portion is allocated "without any
    double-counting". Null references are not keys: they are dropped here (no
    link can name them) and pass through the caller's anti-join intact.
    ``columns`` is the collateral frame's column list, already resolved by the
    caller.
    """
    tie_break = [c for c in ("beneficiary_type", "beneficiary_reference") if c in columns]
    return (
        collateral.filter(pl.col("collateral_reference").is_not_null())
        .with_columns(pl.col("collateral_reference").cast(pl.String), value.alias("_value"))
        .sort(
            ["collateral_reference", "_value", *tie_break],
            nulls_last=True,
            maintain_order=True,
        )
        .unique(subset=["collateral_reference"], keep="first", maintain_order=True)
    )


def _residual_fill(
    coll_refs: list[str],
    ben_types: list[str],
    ben_refs: list[str],
    values: list[float],
    demands: list[float],
    demand_effs: list[float],
) -> list[float]:
    """Greedy two-sided residual fill over pre-ordered link edges.

    Each edge absorbs ``min(item supply remaining, beneficiary demand
    remaining, per-link cap)`` and decrements both residuals, so demand filled
    by one item is invisible to later items (they spill to the next-best
    beneficiary). Returns the allocated slice per edge in the input order;
    ``Σ slices`` for any single item never exceeds its finite value.

    ``values`` / ``demands`` are per-edge but constant within a
    ``collateral_reference`` / ``(beneficiary_type, beneficiary_reference)``
    respectively, so they seed each residual on first sight and the running
    residual is used thereafter. ``demand_effs`` is the per-edge ceiling
    (the ``max_pledge_amount`` sub-limit when present).
    """
    eps = 1e-9
    supply_rem: dict[str, float] = {}
    demand_rem: dict[tuple[str, str], float] = {}
    slices: list[float] = []
    for cref, btype, bref, value, demand, demand_eff in zip(
        coll_refs, ben_types, ben_refs, values, demands, demand_effs, strict=True
    ):
        s_rem = supply_rem.get(cref, value)
        ben_key = (btype, bref)
        d_rem = demand_rem.get(ben_key, demand)
        take = min(s_rem, d_rem, demand_eff)
        if take < eps:
            take = 0.0
        supply_rem[cref] = s_rem - take
        demand_rem[ben_key] = d_rem - take
        slices.append(take)
    return slices
