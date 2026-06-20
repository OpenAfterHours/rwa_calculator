"""
SFT EAD via the Financial Collateral Comprehensive Method (FCCM).

Pipeline position:
    HierarchyResolver -> [CCR pipeline adapter] -> sft_rows_to_exposures
        -> Classifier -> CRMProcessor -> SA/IRB/Slotting Calculators

Key responsibilities:
- Detect SFT rows (``transaction_type == "sft"``) inside the CCR bundle and
  apply the Financial Collateral Comprehensive Method (FCCM) per CRR Art.
  271(2) and Art. 220-223 — rather than the SA-CCR derivative chain
  (Art. 274 / Art. 278).
- Compute the FCCM E* formula at netting-set grain:
      E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))    (Art. 223(5))
  using the standardised supervisory haircuts in
  ``rwa_calc.engine.crm.haircut_tables`` (pack-bound). Haircut scalars and the
  5-business-day liquidation period for SFTs (Art. 224(2)(c)) are sourced from
  the rulepack via that module — no regulatory scalars are declared here per the
  engine/data separation rule.
- Emit one synthetic exposure row per SFT netting set with
  ``ccr_method == "fccm_sft"`` and ``risk_type == "CCR_SFT"`` so downstream
  Classifier / CRM / SA routing treats the row as a vanilla unsecured
  institution / corporate-style exposure whose ``drawn_amount`` already
  carries the post-FCCM EAD.

Scope decisions (kept narrow on purpose; revisit when new SFT scenarios land):
- Single-trade, single-counterparty netting sets only (Art. 220(1)(a)).
- Unmargined SFTs only (Art. 224(2)(c) 5-BD liquidation period default;
  the margined FCCM extension lives in Art. 285 and is not modelled).
- VaR (Art. 221) and IMM (Art. 283) SFT EAD methods are reserved on
  ``SFTConfig.method`` but not implemented.

References:
- CRR Art. 220(1)(a) — single-CP SFT / master-netting-set scope.
- CRR Art. 220(3)(a)(i) — standardised supervisory haircuts.
- CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
- CRR Art. 224(2)(c) — 5-BD liquidation period for SFTs.
- CRR Art. 224 Table 1 — H_10 by collateral type / CQS / residual maturity.
- CRR Art. 226(2) — H_m = H_10 × √(T_m / 10) liquidation-period scaling.
- CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.engine.crm.haircut_tables import (
    FX_HAIRCUT,
    lookup_collateral_haircut,
    scale_haircut_for_liquidation_period,
)
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawCCRBundle, RawSFTBundle

logger = logging.getLogger(__name__)

# CRR Art. 224(2) repo/SFT liquidation period (5 BD), resolved from the common
# pack at module load — feeds the Art. 226(2) sqrt(T_m/10) haircut scaling below.
# Kept int (passed to scale_haircut_for_liquidation_period). (S13-h)
_PACK = resolve("crr", date(2026, 1, 1))
_LIQUIDATION_PERIOD_REPO = _PACK.int_param("liquidation_period_repo").value

# ``"sft"`` is the canonical TRADE_SCHEMA.transaction_type discriminator for
# securities financing transactions per Art. 220(1)(a). Defined once so the
# pipeline adapter and this module agree on the routing token.
SFT_TRANSACTION_TYPE: str = "sft"


# =============================================================================
# Public API
# =============================================================================


@cites("CRR Art. 220")
@cites("CRR Art. 223")
@cites("CRR Art. 224")
@cites("CRR Art. 226")
@cites("CRR Art. 271")
def sft_rows_to_exposures(
    raw_ccr: RawCCRBundle,
    reporting_date: date,
) -> pl.LazyFrame:
    """Shape FCCM SFT EADs into synthetic exposure rows.

    For each netting set whose trades are flagged ``transaction_type == "sft"``,
    compute ``E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))`` (Art. 223(5)) using the
    Art. 224 Table 1 supervisory haircuts scaled to the 5-business-day SFT
    liquidation period (Art. 224(2)(c), Art. 226(2)).

    The function expects ``raw_ccr.trades`` to contain only SFT rows (the
    pipeline adapter splits derivative vs SFT before calling). Each emitted
    synthetic exposure row carries:

        exposure_reference    = "ccr__<netting_set_id>"
        exposure_type         = "ccr_netting_set"
        counterparty_reference= from NETTING_SET_SCHEMA
        risk_type             = "CCR_SFT"
        drawn_amount          = E*  (FCCM EAD)
        interest              = 0.0
        undrawn_amount        = 0.0
        nominal_amount        = 0.0
        currency              = first trade currency in the NS
        value_date            = reporting_date
        maturity_date         = max(trade maturity in the NS)
        seniority             = "senior"
        source_netting_set_id = <netting_set_id>
        ccr_method            = "fccm_sft"
        ead_ccr               = E*  (mirrors drawn_amount for consistency)

    The SA-CCR derivative component columns (``rc_unmargined``, ``pfe_addon``,
    ``pfe_multiplier``, ``addon_aggregate``) are intentionally NOT projected
    here so the downstream ``diagonal_relaxed`` concat at the pipeline level
    fills them as null on SFT rows.

    Args:
        raw_ccr: CCR bundle pre-filtered to SFT trades (and the netting sets
            that own them). Non-SFT rows are tolerated but ignored.
        reporting_date: As-of date; written to ``value_date``.

    Returns:
        LazyFrame at netting-set grain. Empty (zero-row) frame when the
        filtered trades bundle is empty.

    References:
        CRR Art. 271(2); Art. 220(1)(a); Art. 223(5); Art. 224 Table 1;
        Art. 224(2)(c); Art. 226(2).
    """
    trades_lf = raw_ccr.trades.trades
    netting_sets_lf = raw_ccr.netting_sets.netting_sets
    ccr_collateral_lf = raw_ccr.ccr_collateral.ccr_collateral

    # The in-CCR path discriminates SFT rows by ``transaction_type``; the
    # netting-set ``counterparty_reference`` lives on the separate netting-set
    # table. Pre-filter to SFT trades and supply the NS-grain counterparty
    # frame to the shared E* core (Art. 223(5)). The core does the single
    # trade collect the eager HE loop needs.
    sft_trades_lf = trades_lf.filter(pl.col("transaction_type") == SFT_TRANSACTION_TYPE)
    ns_counterparty_lf = netting_sets_lf.select(
        pl.col("netting_set_id"), pl.col("counterparty_reference")
    )
    return _build_sft_exposure_rows(
        sft_trades_lf=sft_trades_lf,
        ns_counterparty_lf=ns_counterparty_lf,
        ccr_collateral_lf=ccr_collateral_lf,
        reporting_date=reporting_date,
    )


@cites("CRR Art. 220")
@cites("CRR Art. 223")
@cites("CRR Art. 224")
@cites("CRR Art. 226")
@cites("CRR Art. 271")
def sft_bundle_to_exposures(
    raw_sft: RawSFTBundle,
    reporting_date: date,
) -> pl.LazyFrame:
    """Shape FCCM SFT EADs into synthetic exposure rows from the lean SFT bundle.

    The peer-subsystem entry point (SFT/FCCM separation Phase 5): consumes the
    dedicated :class:`RawSFTBundle` rather than the co-mingled
    :class:`RawCCRBundle`. The E* math is identical to
    :func:`sft_rows_to_exposures` — only the input plumbing differs:

    - Every trade row is an SFT (no ``transaction_type`` filter): the SFT/
      derivative discrimination has moved out of the engine and into the input
      bundle, so the whole ``raw_sft.trades`` frame is in scope.
    - The netting-set ``counterparty_reference`` is denormalised onto the trade
      row (FCCM scope is single-trade single-counterparty netting sets,
      Art. 220(1)(a)), so the NS-grain counterparty frame is derived from the
      trades themselves rather than a separate netting-set table.
    - Collateral is OPTIONAL (``raw_sft.collateral is None`` for an
      uncollateralised SFT, the common case): a missing collateral leaf yields a
      zero collateral term (CVA·(1−HC−HFX) = 0), exactly as an empty
      ``ccr_collateral`` frame does on the in-CCR path.

    Each emitted synthetic exposure row carries the same provenance as
    :func:`sft_rows_to_exposures` (``exposure_reference = "ccr__<netting_set_id>"``,
    ``risk_type = "CCR_SFT"``, ``ccr_method = "fccm_sft"``, ``drawn_amount = E*``,
    ``ead_ccr = E*``).

    Args:
        raw_sft: The SFT (FCCM) input bundle — every trade row is an SFT with the
            denormalised netting-set counterparty; collateral optional.
        reporting_date: As-of date; written to ``value_date``.

    Returns:
        LazyFrame at netting-set grain. Empty (zero-row) frame when the trades
        bundle is empty.

    References:
        CRR Art. 271(2); Art. 220(1)(a); Art. 223(5); Art. 224 Table 1;
        Art. 224(2)(c); Art. 226(2).
    """
    sft_trades_lf = raw_sft.trades.sft_trades
    # Counterparty is denormalised onto the trade — collapse to NS grain. The
    # ``first()`` aggregation is exact under the single-CP-per-NS scope
    # (Art. 220(1)(a)); should a future netting set span counterparties the
    # FCCM scope itself would need revisiting.
    ns_counterparty_lf = sft_trades_lf.group_by("netting_set_id").agg(
        pl.col("counterparty_reference").first()
    )
    ccr_collateral_lf = (
        raw_sft.collateral.sft_collateral if raw_sft.collateral is not None else None
    )
    return _build_sft_exposure_rows(
        sft_trades_lf=sft_trades_lf,
        ns_counterparty_lf=ns_counterparty_lf,
        ccr_collateral_lf=ccr_collateral_lf,
        reporting_date=reporting_date,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _build_sft_exposure_rows(
    sft_trades_lf: pl.LazyFrame,
    ns_counterparty_lf: pl.LazyFrame,
    ccr_collateral_lf: pl.LazyFrame | None,
    reporting_date: date,
) -> pl.LazyFrame:
    """Compute the FCCM E* per netting set and shape the synthetic rows.

    The single home of the Art. 223(5) E* arithmetic, shared by both the
    in-CCR (:func:`sft_rows_to_exposures`) and peer-subsystem
    (:func:`sft_bundle_to_exposures`) entry points so the regulatory core is
    declared once — including the single trade ``collect()`` the eager HE loop
    requires. The two callers differ only in how they shape the three inputs.

    Args:
        sft_trades_lf: SFT trade rows (already filtered to SFTs), carrying
            ``netting_set_id``, ``notional``, ``currency``, ``maturity_date``
            and the three Art. 223(5) HE columns. Materialised once here for
            the per-row HE lookup (SFT books are firm-scale, tens to hundreds
            of rows).
        ns_counterparty_lf: Netting-set-grain frame mapping ``netting_set_id``
            to ``counterparty_reference`` (the synthetic row's counterparty).
        ccr_collateral_lf: Netting-set-keyed collateral feeding the
            ``CVA·(1−HC−HFX)`` term, or ``None`` for an uncollateralised book.
        reporting_date: As-of date; written to ``value_date``.

    Returns:
        LazyFrame at netting-set grain with the FCCM provenance columns.

    References:
        CRR Art. 223(5); Art. 224 Table 1; Art. 224(2)(c); Art. 226(2).
    """
    # Materialise the SFT trade frame once for the per-row HE lookup (the eager
    # divergence both entry points share — kept in one place).
    sft_trades_df = sft_trades_lf.collect()
    trade_schema = sft_trades_df.columns
    coll_schema = (
        ccr_collateral_lf.collect_schema().names() if ccr_collateral_lf is not None else []
    )

    # ---- 1) Per-trade E·(1+HE) -------------------------------------------------
    # HE is per-row (depends on the security being lent / sold), so we
    # materialise the SFT trade frame once to compute HE row-by-row via the
    # supervisory haircut lookup. SFT books are small (firm-scale; tens to
    # hundreds of rows per netting set) so collecting here is cheap relative
    # to building a 5-band x CQS x type expression chain in Polars.
    he_values: list[float] = []
    for row in sft_trades_df.iter_rows(named=True):
        he_values.append(
            _compute_exposure_haircut(
                collateral_type=row.get("exposure_collateral_type")
                if "exposure_collateral_type" in trade_schema
                else None,
                cqs=row.get("exposure_security_cqs")
                if "exposure_security_cqs" in trade_schema
                else None,
                residual_maturity_years=row.get("exposure_security_residual_maturity_years")
                if "exposure_security_residual_maturity_years" in trade_schema
                else None,
            )
        )
    sft_trades_with_he = sft_trades_df.with_columns(
        pl.Series("_he", he_values, dtype=pl.Float64),
    ).with_columns(
        (pl.col("notional").fill_null(0.0) * (1.0 + pl.col("_he"))).alias("_e_times_one_plus_he"),
    )

    # ---- 2) Per-NS sum (single-trade NSes today but stay aggregation-safe) ----
    ns_e_grossed = (
        sft_trades_with_he.group_by("netting_set_id")
        .agg(
            [
                pl.col("_e_times_one_plus_he").sum().alias("_e_grossed"),
                pl.col("currency").first().alias("_trade_currency"),
                pl.col("maturity_date").max().alias("_trade_max_maturity"),
            ]
        )
        .lazy()
    )

    # ---- 3) Per-NS collateral CVA·(1−HC−HFX) ---------------------------------
    has_collateral_rows = (
        ccr_collateral_lf is not None
        and "netting_set_id" in coll_schema
        and "market_value" in coll_schema
    )
    if has_collateral_rows:
        # Materialise to apply per-row supervisory haircut lookups against the
        # Art. 224 table. Same scale rationale as the trade frame above.
        coll_df = ccr_collateral_lf.collect()
        if coll_df.is_empty():
            cva_per_ns: pl.LazyFrame = ns_e_grossed.select(pl.col("netting_set_id")).with_columns(
                pl.lit(0.0).alias("_cva_net")
            )
        else:
            # Join trade currency onto the collateral frame for the same-currency
            # HFX shortcut (Art. 224 Table 4: HFX=0 when collateral currency
            # equals exposure currency).
            ns_currency_df = sft_trades_with_he.group_by("netting_set_id").agg(
                pl.col("currency").first().alias("_trade_currency"),
            )
            coll_with_ccy = coll_df.join(ns_currency_df, on="netting_set_id", how="left")
            cva_values: list[float] = []
            for row in coll_with_ccy.iter_rows(named=True):
                cva_values.append(
                    _compute_collateral_cva_contribution(
                        collateral_type=row.get("collateral_type"),
                        market_value=row.get("market_value") or 0.0,
                        cqs=row.get("issuer_cqs"),
                        residual_maturity_years=row.get("residual_maturity_years"),
                        collateral_currency=row.get("currency"),
                        exposure_currency=row.get("_trade_currency"),
                    )
                )
            cva_per_ns = (
                coll_with_ccy.with_columns(pl.Series("_cva_contrib", cva_values, dtype=pl.Float64))
                .group_by("netting_set_id")
                .agg(pl.col("_cva_contrib").sum().alias("_cva_net"))
                .lazy()
            )
    else:
        cva_per_ns = ns_e_grossed.select(
            pl.col("netting_set_id"),
            pl.lit(0.0).alias("_cva_net"),
        )

    # ---- 4) Compose NS-grain frame and compute E* ----------------------------
    sft_ns_ids = sft_trades_df["netting_set_id"].unique().to_list()
    ns_with_ead = (
        ns_counterparty_lf.filter(pl.col("netting_set_id").is_in(sft_ns_ids))
        .join(ns_e_grossed, on="netting_set_id", how="left")
        .join(cva_per_ns, on="netting_set_id", how="left")
        .with_columns(
            [
                pl.col("_e_grossed").fill_null(0.0),
                pl.col("_cva_net").fill_null(0.0),
            ]
        )
        .with_columns(
            pl.max_horizontal(
                pl.col("_e_grossed") - pl.col("_cva_net"),
                pl.lit(0.0),
            ).alias("ead_ccr")
        )
    )

    # ---- 5) Shape into synthetic exposure rows -------------------------------
    select_exprs = [
        pl.concat_str([pl.lit("ccr__"), pl.col("netting_set_id")]).alias("exposure_reference"),
        pl.lit("ccr_netting_set").alias("exposure_type"),
        pl.col("counterparty_reference"),
        pl.lit(reporting_date).alias("value_date"),
        pl.col("_trade_max_maturity").alias("maturity_date"),
        pl.col("_trade_currency").alias("currency"),
        pl.col("ead_ccr").alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.lit("senior").alias("seniority"),
        pl.lit("CCR_SFT").alias("risk_type"),
        pl.col("netting_set_id").alias("source_netting_set_id"),
        pl.lit("fccm_sft").alias("ccr_method"),
        pl.col("ead_ccr"),
    ]
    # Drop helper "_*" columns from the public projection.
    return ns_with_ead.select(select_exprs)


def _lookup_haircut_unscaled(
    collateral_type: str | None,
    cqs: int | None,
    residual_maturity_years: float | None,
) -> float | None:
    """Look up the 10-BD base supervisory haircut for collateral / exposure
    security per CRR Art. 224 Table 1, without applying liquidation-period
    scaling.

    Returns ``None`` when the security is ineligible under Art. 197 (e.g.
    unrated corporate bonds), distinguishing that from a legitimately-zero
    haircut (cash). The 5-BD SFT scaling is applied by the caller via
    :func:`scale_haircut_for_liquidation_period` so that the SFT EAD formula
    sees the un-rounded ``H_10 × √(5/10)`` value (the table-level lookup
    helper rounds to 6 decimals at the scaled step, which would exceed the
    1 ppm tolerance pinned by the CCR-A12 golden after net of collateral).
    """
    if collateral_type is None:
        return 0.0
    base = lookup_collateral_haircut(
        collateral_type=collateral_type,
        cqs=int(cqs) if cqs is not None else None,
        residual_maturity_years=float(residual_maturity_years)
        if residual_maturity_years is not None
        else None,
        is_basel_3_1=False,
        liquidation_period_days=10,  # un-scaled base; we apply scaling below
    )
    return float(base) if base is not None else None


def _compute_exposure_haircut(
    collateral_type: str | None,
    cqs: int | None,
    residual_maturity_years: float | None,
) -> float:
    """Compute HE for the exposure-side security per Art. 224 Table 1, scaled
    to the 5-BD SFT liquidation period (Art. 224(2)(c) + Art. 226(2)).

    Returns 0.0 when ``collateral_type`` is None (no security info → treat
    as cash-equivalent / no haircut); the upstream test fixture pins this
    to ``"corp_bond"`` so the no-collateral-type branch is purely defensive.
    """
    base = _lookup_haircut_unscaled(collateral_type, cqs, residual_maturity_years)
    if base is None or base == 0.0:
        return 0.0
    return scale_haircut_for_liquidation_period(base, _LIQUIDATION_PERIOD_REPO)


def _compute_collateral_cva_contribution(
    collateral_type: str | None,
    market_value: float,
    cqs: int | None,
    residual_maturity_years: float | None,
    collateral_currency: str | None,
    exposure_currency: str | None,
) -> float:
    """Compute one collateral row's contribution to ``CVA·(1−HC−HFX)``.

    HC sourced from Art. 224 Table 1 (unscaled lookup) and scaled to the 5-BD
    SFT liquidation period (Art. 224(2)(c), Art. 226(2)). HFX is 0% when the
    collateral and exposure currencies match (Art. 224 Table 4), else the
    8% base FX haircut scaled to 5 BD.
    """
    if collateral_type is None:
        # No collateral type → cannot value the collateral conservatively;
        # treat as ineligible (zero recognition).
        return 0.0
    base = _lookup_haircut_unscaled(collateral_type, cqs, residual_maturity_years)
    if base is None:
        # Ineligible collateral per Art. 197 — zero recognition.
        return 0.0
    hc = scale_haircut_for_liquidation_period(base, _LIQUIDATION_PERIOD_REPO)
    same_currency = (
        collateral_currency is not None
        and exposure_currency is not None
        and collateral_currency.upper() == exposure_currency.upper()
    )
    if same_currency:
        hfx = 0.0
    else:
        hfx = scale_haircut_for_liquidation_period(float(FX_HAIRCUT), _LIQUIDATION_PERIOD_REPO)
    return float(market_value) * (1.0 - hc - hfx)
