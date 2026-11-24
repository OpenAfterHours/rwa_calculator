"""
Output floor application and impact analysis (Basel 3.1).

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator (floor) -> AggregatedResultBundle

Key responsibilities:
- Portfolio-level output floor: TREA = max(U-TREA, x * S-TREA + OF-ADJ), both
  legs taken over the whole priced book (P1.367)
- OF-ADJ computation, and the GCRA cap base it is capped against (P1.212)
- Pro-rata shortfall distribution across floor-eligible (modelled) exposures
- Per-exposure floor impact analysis for COREP reporting
- OutputFloorSummary with U-TREA, S-TREA, OF-ADJ, and shortfall

Both legs of the Art. 92(2A) max are whole-entity aggregates. Paragraph 3 builds
U-TREA from points (a)-(f) "in respect of all the business activities of an
institution"; paragraph 3A builds S-TREA as the same sum "calculated without
using ... the IRB Approach". So every row the engine prices is in BOTH legs: a
modelled row (IRB, slotting, CCR-via-SA - ``FLOOR_ELIGIBLE_APPROACHES``) at its
own RWEA in U-TREA and its ``sa_rwa`` in S-TREA; every other row (standardised,
equity, and any unrecognised label, which is not modelled and so is standardised
by construction) at its own RWEA in both. The BA-CVA RWEA (paragraph 3(d), x 12.5
by paragraph 4(b), not on the 3A exclusion list) is passed in and added to both
legs too. The SA book cancels out of the comparison only at x = 1; at x < 1 it
lowers the floor's bite by (1 - x) of itself, which the engine's former
modelled-subset formula withheld.

Scope: the engine prices credit risk (the OF 02.00 credit-risk rows) and BA-CVA.
Market, operational and Art. 378 settlement risk beyond the ledger's own rows are
not priced here, so the max is Art. 92's max over the components this engine
prices, not the entity's whole TREA.

When the floor binds, the shortfall is distributed pro-rata to each floor-eligible
exposure by its ``sa_rwa``; standardised and equity rows keep their own RWEA. The
article does not say how to allocate the add-on: this is the recorded firm choice
(P1.367 owner sign-off), kept here so the per-row ``rwa_final`` still foots.

OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2) reconciles the
different provision treatments between IRB and SA so the floor comparison
is on a like-for-like basis.  Without OF-ADJ, the floor penalises IRB
banks that have EL shortfall (CET1 deduction) while giving no credit for
excess provisions (T2 addition), and vice versa for SA general provisions.
GCRA enters capped at 1.25% of the paragraph-3A risk-weighted exposure amounts
(:func:`gcra_cap_base`) - the credit and counterparty-credit RWEA of the whole
book at its standardised value, NOT S-TREA, which also holds the paragraph 3(ca)
settlement own-funds lines and the CVA requirement.

References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
- PRA PS1/26 Art. 92 para 3 / 3A / 4: the two legs, whole-firm by construction
- PRA PS1/26 Art. 92 para 2A: OF-ADJ = 12.5 * (IRB T2 - IRB CET1 - GCRA + SA T2)
- PRA PS1/26 Art. 62(d): IRB T2 credit (excess provisions, capped at 0.6% of IRB RWA)
- PRA PS1/26 Art. 36(1)(d), Art. 40: IRB CET1 deductions (EL shortfall)
- PRA PS1/26 Art. 62(c): SA T2 credit (general credit risk adjustments)
- PRA PS1/26 Art. 122(8): for unrated corporates on the IRB Approach, S-TREA
  takes (a) 100% or (b) 65%/135% from the firm's IG assessment — chosen by
  ``output_floor_investment_grade_election`` and already applied to ``sa_rwa``
  upstream (engine/sa/investment_grade.py); this module never reads it
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation

Internal module — not part of the public API.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.engine.aggregator._schemas import (
    EQUITY_APPROACHES,
    FLOOR_ELIGIBLE_APPROACHES,
    FLOOR_IMPACT_SCHEMA,
)
from rwa_calc.engine.aggregator._utils import (
    col_or_default,
    collect_views,
    empty_frame,
    resolve_rwa_col,
)
from rwa_calc.engine.ccr.failed_trades import is_dvp_own_funds_line
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

#: The column every floor partition keys on.
APPROACH_COL = "approach_applied"


def compute_of_adj(
    irb_t2_credit: float,
    irb_cet1_deduction: float,
    gcra_amount: float,
    sa_t2_credit: float,
    gcra_cap_base: float,
    *,
    pack: ResolvedRulepack | None = None,
) -> tuple[float, float]:
    """Compute OF-ADJ per PRA PS1/26 Art. 92 para 2A.

    OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2)

    GCRA is capped at 1.25% of the paragraph-3A risk-weighted exposure amounts
    (:func:`gcra_cap_base`) before entering the formula.

    Args:
        irb_t2_credit: Art. 62(d) IRB T2 credit (capped at 0.6% of IRB RWA).
        irb_cet1_deduction: Art. 36(1)(d) + Art. 40 CET1 deductions.
        gcra_amount: General credit risk adjustments (gross of tax).
        sa_t2_credit: Art. 62(c) SA T2 credit.
        gcra_cap_base: The paragraph-3A risk-weighted exposure amounts the GCRA
            cap is 1.25% of — see :func:`gcra_cap_base`.
        pack: Resolved rulepack supplying the ``gcra_cap_rate`` scalar. The
            output floor is Basel-3.1-only, so the no-pack fallback resolves the
            b31 regime (used by direct unit tests that pass no pack).

    Returns:
        Tuple of (of_adj, gcra_capped) where gcra_capped is the GCRA after
        applying the cap.
    """
    # The GCRA cap rate (Art. 92 para 2A) is a Basel-3.1 pack scalar; the output
    # floor is b31-only, so the no-pack fallback resolves the b31 regime.
    # scalar_value is the compile-boundary Decimal->float conversion.
    resolved_pack = pack if pack is not None else resolve("b31", date(2027, 1, 1))
    gcra_cap_rate = scalar_value(resolved_pack.scalar_param("gcra_cap_rate"))

    # Cap GCRA per Art. 92 para 2A. When the base is 0 the cap is 0.0, so
    # gcra_capped collapses to 0.0 (GCRA is always >= 0, hence min(x, 0.0) ==
    # 0.0). The cap is applied unconditionally — guarding on `gcra_cap > 0` would
    # leak the full uncapped GCRA at a zero base.
    gcra_cap = gcra_cap_base * gcra_cap_rate
    gcra_capped = min(gcra_amount, gcra_cap)
    of_adj = 12.5 * (irb_t2_credit - irb_cet1_deduction - gcra_capped + sa_t2_credit)
    return of_adj, gcra_capped


@cites("PS1/26, paragraph 92")
def gcra_cap_base(combined: pl.LazyFrame, column_names: set[str]) -> float:
    """The paragraph-3A risk-weighted exposure amounts the GCRA cap is 1.25% of.

    PS1/26 Art. 92(2A): GCRA is general credit risk adjustments "of up to 1.25%
    of risk-weighted exposure amounts calculated in accordance with paragraph
    3A". Paragraph 3A is paragraph 3's sum for all the business activities of the
    institution, calculated without the IRB Approach, and the RISK-WEIGHTED
    EXPOSURE AMOUNTS in that sum are points (a) and (f) — credit, dilution and
    counterparty credit risk, including "Articles 379 and 380 of CRR". So the
    base is every row's :func:`standardised_rwea` — modelled rows at their
    ``sa_rwa``, standardised and equity rows at their own RWEA, CCR and
    default-fund rows, Art. 379 Column 4 free deliveries — EXCEPT the Art. 378
    DvP settlement lines, which are own-funds requirements under point (ca), not
    risk-weighted exposure amounts. It is NOT S-TREA, which holds those (ca)
    lines and the CVA requirement as well; never pass the floor's S-TREA here.

    Needed one step before :func:`apply_floor_with_impact`, because the capped
    GCRA is an input to OF-ADJ and OF-ADJ an input to the floor. A non-finite
    figure counts as zero, so one poisoned row cannot turn the base into NaN —
    ``min(gcra, NaN)`` would leave GCRA uncapped. Read pre-floor, so the own
    RWEA carrier is ``rwa_final``. A frame with no approach column cannot be
    floored at all and has no base.

    References:
        PRA PS1/26 Art. 92(2A), 92(3)(a), 92(3)(ca), 92(3A); CRR Art. 378, 379.
    """
    if APPROACH_COL not in column_names:
        return 0.0
    sa_col = "sa_rwa" if "sa_rwa" in column_names else "rwa_final"
    in_base = ~is_dvp_own_funds_line(column_names)
    totals = collect_views(
        {
            "base": combined.filter(in_base).select(
                standardised_rwea("rwa_final", sa_col).sum().alias("base")
            )
        }
    )["base"]
    value = totals.get_column("base").item() if totals.height else None
    return float(value) if value is not None else 0.0


def standardised_rwea(own_rwa_col: str, sa_rwa_col: str = "sa_rwa") -> pl.Expr:
    """One row's contribution to the paragraph-3A (standardised) aggregates.

    A modelled row (``FLOOR_ELIGIBLE_APPROACHES``: IRB, slotting, CCR-via-SA)
    contributes its SA-equivalent ``sa_rwa``. Every other row is not modelled and
    so is standardised by construction — standardised, equity, and any label the
    modelled set does not name, exactly as OF 02.01 column 0020 takes the
    COMPLEMENT of the modelled set — and contributes its own RWEA, which is what
    keeps an SA row's contribution to S-TREA identical to its contribution to
    U-TREA. A null or non-finite figure contributes 0.0.
    """
    is_modelled = pl.col(APPROACH_COL).is_in(list(FLOOR_ELIGIBLE_APPROACHES))
    carrier = pl.when(is_modelled).then(pl.col(sa_rwa_col)).otherwise(pl.col(own_rwa_col))
    return pl.when(carrier.is_finite()).then(carrier).otherwise(0.0)


@cites("PS1/26, paragraph 92")
def apply_floor_with_impact(
    combined: pl.LazyFrame,
    sa_results: pl.LazyFrame,
    floor_pct: float,
    of_adj: float = 0.0,
    irb_t2_credit: float = 0.0,
    irb_cet1_deduction: float = 0.0,
    gcra_amount: float = 0.0,
    sa_t2_credit: float = 0.0,
    cva_rwa: float = 0.0,
) -> tuple[pl.LazyFrame, pl.LazyFrame, OutputFloorSummary]:
    """
    Apply portfolio-level output floor and generate impact analysis.

    The floor is applied at portfolio level per PRA PS1/26 Art. 92 para 2A:
    ``TREA = max(U-TREA, x * S-TREA + OF-ADJ)``, both legs over the whole priced
    book plus ``cva_rwa`` (module docstring). When the floor binds, the shortfall
    (``x * S-TREA + OF-ADJ - U-TREA``) is distributed pro-rata across the
    floor-eligible exposures (IRB + slotting + CCR-via-SA) by each exposure's
    ``sa_rwa``; standardised and equity rows keep their own RWEA.

    Args:
        combined: Combined results with ``rwa_final`` column.
        sa_results: SA results to derive floor RWA from.
        floor_pct: Floor percentage (e.g. 0.725 for 72.5%).
        of_adj: Pre-computed OF-ADJ amount (default 0.0 for backward compat).
        irb_t2_credit: Art. 62(d) IRB T2 credit (for summary reporting).
        irb_cet1_deduction: Art. 36(1)(d) + Art. 40 CET1 deductions (for summary).
        gcra_amount: GCRA after cap (for summary reporting).
        sa_t2_credit: Art. 62(c) SA T2 credit (for summary reporting).
        cva_rwa: The BA-CVA RWEA (Art. 92(3)(d) x 12.5), added to BOTH legs. It
            stays a separate scalar: it is in neither ``rwa_final`` nor
            ``total_rwa_post_floor``, and it never takes a share of the shortfall.

    Returns:
        Tuple of (floored results, floor impact analysis, portfolio summary).
    """
    # Ensure combined has rwa_final column
    combined_cols = set(combined.collect_schema().names())
    if "rwa_final" not in combined_cols:
        rwa_col = resolve_rwa_col(combined_cols)
        if rwa_col:
            combined = combined.with_columns(pl.col(rwa_col).alias("rwa_final"))
        else:
            combined = combined.with_columns(pl.lit(0.0).alias("rwa_final"))

    # Store pre-floor RWA for impact calculation
    combined = combined.with_columns(pl.col("rwa_final").alias("rwa_pre_floor"))

    # Get SA RWA for each exposure. If calculate_unified already stored
    # sa_rwa inline (single-pass path), use it directly. Otherwise join
    # from the separate SA results frame (aggregate_with_audit path).
    combined_cols = set(combined.collect_schema().names())
    if "sa_rwa" in combined_cols:
        result = combined
    else:
        sa_cols = set(sa_results.collect_schema().names())
        sa_rwa_col = resolve_rwa_col(sa_cols)
        if not sa_rwa_col:
            sa_rwa_total, equity_rwa_total = _portfolio_sa_equity_totals(combined)
            summary = OutputFloorSummary(
                u_trea=0.0,
                s_trea=0.0,
                floor_pct=floor_pct,
                floor_threshold=0.0,
                shortfall=0.0,
                portfolio_floor_binding=False,
                floored_modelled_rwa=0.0,
                of_adj=of_adj,
                irb_t2_credit=irb_t2_credit,
                irb_cet1_deduction=irb_cet1_deduction,
                gcra_amount=gcra_amount,
                sa_t2_credit=sa_t2_credit,
                sa_rwa_total=sa_rwa_total,
                equity_rwa_total=equity_rwa_total,
                total_rwa_post_floor=sa_rwa_total + equity_rwa_total,
                cva_rwa=cva_rwa,
            )
            return combined, empty_frame(FLOOR_IMPACT_SCHEMA), summary

        sa_rwa = sa_results.select(
            pl.col("exposure_reference"),
            pl.col(sa_rwa_col).alias("sa_rwa"),
        )
        result = combined.join(sa_rwa, on="exposure_reference", how="left", suffix="_sa")

    # --- Portfolio-level output floor (Art. 92 para 2A) ---
    #
    # 1. Both legs over the whole book (paras 3 / 3A): U-TREA sums every row's
    #    own RWEA, S-TREA every row's standardised RWEA (``standardised_rwea``),
    #    and the CVA RWEA joins both. The SA and equity books are in both legs —
    #    they cancel out of the comparison only at x = 1.
    #
    # 2. Floor threshold = x * S-TREA + OF-ADJ.  OF-ADJ reconciles the
    #    different provision treatments (IRB EL vs SA general CRA).
    #
    # 3. If floor binds (threshold > U-TREA), distribute the shortfall
    #    pro-rata over the floor-eligible rows by each one's sa_rwa share of
    #    the modelled book's SA-equivalent.
    #
    # 4. Per-exposure columns: floor_rwa, floor_impact_rwa, is_floor_binding,
    #    rwa_final (post-floor), output_floor_pct for COREP reporting.
    floor_eligible_approaches = list(FLOOR_ELIGIBLE_APPROACHES)
    is_eligible = pl.col(APPROACH_COL).is_in(floor_eligible_approaches)
    is_equity = pl.col(APPROACH_COL).is_in(list(EQUITY_APPROACHES))
    # Non-finite guard: Polars float ``.sum()`` propagates NaN, so one poisoned
    # row would turn U-TREA/S-TREA — and through the pro-rata shortfall every
    # eligible row's post-floor rwa_final — into NaN. A non-finite ``sa_rwa``
    # follows the existing null convention (counts as 0 in S-TREA); a row whose
    # ``rwa_pre_floor`` is non-finite is excluded from the floor computation
    # entirely — no share, no total contribution — and keeps its own value,
    # which the aggregator's AGG001 scan reports per-row.
    sa_rwa_filled = pl.when(pl.col("sa_rwa").is_finite()).then(pl.col("sa_rwa")).otherwise(0.0)
    pre_floor_finite = pl.col("rwa_pre_floor").is_finite().fill_null(value=False)
    is_eligible_finite = is_eligible & pre_floor_finite
    own = pl.col("rwa_pre_floor")

    # Step 1: the portfolio aggregates (one collect — acceptable at the
    # aggregator boundary per project convention). The ledger partitions three
    # ways — modelled, equity, and the standardised remainder (every other row)
    # — so the three own-RWEA totals add back to U-TREA less the CVA RWEA, and
    # ``total_rwa_post_floor`` foots to Σ rwa_final. Every sum is 0.0 over an
    # empty frame.
    totals = (
        result.select(
            _masked_sum(own, pre_floor_finite).alias("own"),
            _masked_sum(standardised_rwea("rwa_pre_floor"), pre_floor_finite).alias("standardised"),
            _masked_sum(sa_rwa_filled, is_eligible_finite).alias("modelled_sa"),
            _masked_sum(own, is_eligible_finite).alias("modelled_own"),
            _masked_sum(own, ~is_eligible & ~is_equity & pre_floor_finite).alias("sa_own"),
            _masked_sum(own, is_equity & pre_floor_finite).alias("equity_own"),
        )
        .collect()
        .row(0, named=True)
    )

    # Step 2: Floor threshold = x * S-TREA + OF-ADJ, and the shortfall.
    u_trea = float(totals["own"]) + cva_rwa
    s_trea = float(totals["standardised"]) + cva_rwa
    floor_threshold = s_trea * floor_pct + of_adj
    shortfall = max(floor_threshold - u_trea, 0.0)
    binding = floor_threshold > u_trea
    modelled_sa = float(totals["modelled_sa"])

    # Step 3: Each eligible exposure's share of the modelled SA-equivalent. With
    # no modelled SA-equivalent there is nothing to carry the add-on, so it is
    # stated on the summary and allocated to no row.
    sa_share = (
        pl.when(is_eligible_finite).then(sa_rwa_filled / pl.lit(modelled_sa)).otherwise(0.0)
        if modelled_sa > 0
        else pl.lit(0.0)
    )
    result = (
        result
        # Step 4: Per-exposure floor columns
        .with_columns(
            (sa_rwa_filled * floor_pct).alias("floor_rwa"),
            pl.lit(floor_pct).alias("output_floor_pct"),
            # Pro-rata add-on: shortfall × this exposure's modelled S-TREA share
            pl.when(is_eligible_finite)
            .then(pl.lit(shortfall) * sa_share)
            .otherwise(0.0)
            .alias("floor_impact_rwa"),
            # Portfolio-level binding flag (same for all eligible rows)
            pl.when(is_eligible_finite)
            .then(pl.lit(binding))
            .otherwise(pl.lit(False))
            .alias("is_floor_binding"),
        )
        # Step 5: Final RWA = pre-floor + pro-rata add-on. A non-finite
        # pre-floor row keeps its own (AGG001-flagged) value untouched.
        .with_columns(
            pl.when(is_eligible_finite)
            .then(pl.col("rwa_pre_floor") + pl.col("floor_impact_rwa"))
            .otherwise(pl.col("rwa_pre_floor"))
            .alias("rwa_final"),
        )
    )

    sa_rwa_total = float(totals["sa_own"])
    equity_rwa_total = float(totals["equity_own"])
    floored_modelled_rwa = float(totals["modelled_own"]) + shortfall
    summary = OutputFloorSummary(
        u_trea=u_trea,
        s_trea=s_trea,
        floor_pct=floor_pct,
        floor_threshold=floor_threshold,
        shortfall=shortfall,
        portfolio_floor_binding=binding,
        floored_modelled_rwa=floored_modelled_rwa,
        of_adj=of_adj,
        irb_t2_credit=irb_t2_credit,
        irb_cet1_deduction=irb_cet1_deduction,
        gcra_amount=gcra_amount,
        sa_t2_credit=sa_t2_credit,
        sa_rwa_total=sa_rwa_total,
        equity_rwa_total=equity_rwa_total,
        total_rwa_post_floor=floored_modelled_rwa + sa_rwa_total + equity_rwa_total,
        cva_rwa=cva_rwa,
    )

    # Generate floor impact analysis (floor-eligible rows only)
    result_cols = set(result.collect_schema().names())
    floor_impact = result.select(
        pl.col("exposure_reference"),
        pl.col(APPROACH_COL),
        col_or_default("exposure_class", result_cols),
        pl.col("rwa_pre_floor"),
        pl.col("floor_rwa"),
        pl.col("is_floor_binding"),
        pl.col("floor_impact_rwa"),
        pl.col("rwa_final").alias("rwa_post_floor"),
        pl.col("output_floor_pct"),
    ).filter(pl.col(APPROACH_COL).is_in(floor_eligible_approaches))

    return result, floor_impact, summary


def _masked_sum(value: pl.Expr, mask: pl.Expr) -> pl.Expr:
    """Σ ``value`` over the rows ``mask`` admits — 0.0 over an empty frame."""
    return pl.when(mask).then(value).otherwise(0.0).sum()


def _portfolio_sa_equity_totals(combined: pl.LazyFrame) -> tuple[float, float]:
    """Sum ``rwa_final`` across standardised and equity rows for the portfolio total.

    Used by the early-return path of :func:`apply_floor_with_impact` when SA
    results are unavailable but the combined frame may still contain SA or
    equity rows that must be reflected in ``total_rwa_post_floor`` (P2.20).
    "Standardised" is the same partition the main path uses: every row that is
    neither modelled nor equity.

    Returns ``(0.0, 0.0)`` when the frame lacks the required columns.
    """
    cols = set(combined.collect_schema().names())
    if APPROACH_COL not in cols or "rwa_final" not in cols:
        return 0.0, 0.0

    is_equity = pl.col(APPROACH_COL).is_in(list(EQUITY_APPROACHES))
    is_sa = ~pl.col(APPROACH_COL).is_in(list(FLOOR_ELIGIBLE_APPROACHES)) & ~is_equity
    # Non-finite rwa_final rows count as 0 here — one NaN row must not blank
    # the portfolio totals (the per-row value is still AGG001-reported).
    rwa_finite = pl.col("rwa_final").is_finite().fill_null(value=False)
    totals = combined.select(
        pl.when(is_sa & rwa_finite)
        .then(pl.col("rwa_final"))
        .otherwise(0.0)
        .sum()
        .fill_null(0.0)
        .alias("sa_total"),
        pl.when(is_equity & rwa_finite)
        .then(pl.col("rwa_final"))
        .otherwise(0.0)
        .sum()
        .fill_null(0.0)
        .alias("equity_total"),
    ).collect()
    return float(totals["sa_total"][0]), float(totals["equity_total"][0])
