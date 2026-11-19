"""
SFT EAD via the Financial Collateral Comprehensive Method (FCCM).

Pipeline position:
    HierarchyResolver -> ccr_sa_ccr -> sft_fccm -> Classifier
        -> CRMProcessor -> SA/IRB/Slotting Calculators

Key responsibilities:
- Consume the dedicated ``RawSFTBundle`` (``RawDataBundle.sft``) and apply the
  Financial Collateral Comprehensive Method (FCCM) per CRR Art. 271(2) and
  Art. 220-223 — rather than the SA-CCR derivative chain (Art. 274 / Art. 278).
- Compute the FCCM E* formula at netting-set grain:
      E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))    (Art. 223(5))
  using the standardised supervisory haircuts in
  ``rwa_calc.engine.crm.haircut_tables`` (pack-bound). Haircut scalars, the
  5-business-day repo liquidation period (Art. 224(2)(b)) and the Art. 285 MPOR
  floors / dispute multiplier are sourced from the rulepack via that module and
  the pack reads below — no regulatory scalars are declared here per the
  engine/data separation rule.
- Price HE and HC from the RUN regime's Art. 224 table: the cited pack Feature
  ``collateral_haircut_maturity_bands_revised`` selects the PS1/26 Art. 224
  Tables 1/3 (five maturity bands; equity 20%/30%, gold 20%) over the CRR ones.
- Recognise financial collateral only (Art. 223(1) "when valuing financial
  collateral"; Art. 197/198): a collateral type outside
  ``data/schemas.py::SFT_FCCM_HAIRCUT_LOOKUP_TYPES``, or a debt security failing
  the Art. 197(1)(b)-(d) CQS test, contributes nothing and raises CCR027. A
  non-eligible security LENT takes the Art. 224(4) non-main-index listed equity
  haircut (as a floor on any higher fall-through value), never HE = 0.
- Net a multi-trade netting set only under an eligible bilateral master netting
  agreement (Art. 220(1), 206; PS1/26 Art. 111(2A)); otherwise each trade is its
  own exposure — ``engine/sft/netting.py::apply_sft_netting_gate`` (CCR028 /
  CCR029).
- Emit one synthetic exposure row per (post-gate) SFT netting set with
  ``ccr_method == "fccm_sft"`` and ``risk_type == "CCR_SFT"`` so downstream
  Classifier / CRM / SA routing treats the row as a vanilla unsecured
  institution / corporate-style exposure whose ``drawn_amount`` already
  carries the post-FCCM EAD.

Scope decisions (kept narrow on purpose; revisit when new SFT scenarios land):
- A netted set (eligible MNA) uses the gross Sum E(1+HE) − Sum C(1−HC−HFX),
  never below the Art. 220(3) net-position formula, which is not modelled.
- BOTH branches modelled (margined/unmargined select on ``is_margined``):
  - (a) Unmargined / simply-collateralised: T_M = 5-BD repo liquidation period
    (Art. 224(2)(b)), with the Art. 226 non-daily revaluation scale-up
    √((N_R+T_M−1)/T_M) driven by ``remargining_frequency_days`` (collapses to
    1.0 at daily revaluation — the regression anchor).
  - (b) Margined (qualifying Art. 285(2)-(4) agreement): T_M = MPOR
    (= F + N − 1, Art. 285(5)), with the Art. 226 non-daily term suppressed
    (the MPOR already encodes the remargin period N).
- Art. 227(2)(a)-(h) 0% core-market-participant carve-out is NOT modelled
  (deferred — needs the full eight-condition gate).
- VaR (Art. 221) and IMM (Art. 283) SFT EAD methods are reserved on
  ``SFTConfig.method`` but not implemented.

References:
- CRR / PS1/26 Art. 220(1) — netted E* only under an eligible MNA (Art. 206).
- CRR Art. 220(3)(a)(i) — standardised supervisory haircuts.
- CRR / PS1/26 Art. 223(1) — volatility adjustments value FINANCIAL collateral.
- CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
- CRR Art. 224(2) — liquidation-period rescale; Art. 224(2)(b) 5-BD repo.
- CRR Art. 224 Table 1 — H_10 by collateral type / CQS / residual maturity;
  PS1/26 Art. 224(1) Tables 1/3 — the Basel 3.1 values and five bands.
- CRR / PS1/26 Art. 224(4) — non-eligible securities lent: non-main-index
  listed equity volatility adjustment.
- CRR Art. 226 — H = H_10 × √(T_M/10) × √((N_R+T_M−1)/T_M) non-daily scale-up.
- CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
- CRR Art. 285(2)-(5) — margined MPOR floors / dispute doubling / F + N − 1.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_SFT_COLLATERAL_NOT_RECOGNISED, CalculationError
from rwa_calc.data.schemas import SFT_FCCM_HAIRCUT_LOOKUP_TYPES
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.crm.haircut_tables import (
    FX_HAIRCUT,
    lookup_collateral_haircut,
    scale_haircut_for_liquidation_period,
    scale_haircut_for_non_daily_revaluation,
)
from rwa_calc.engine.sft.netting import apply_sft_netting_gate
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawSFTBundle
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# CRR Art. 224(2)(b) repo/SFT liquidation period (5 BD), resolved from the common
# pack at module load — feeds the Art. 226 sqrt(T_m/10) haircut scaling below.
# The Art. 285 MPOR floors (F = 5/10/20 BD by transaction-type category) and the
# Art. 285(4) dispute-doubling multiplier (2) are read here too, for the margined
# branch's MPOR = F·mult + N − 1 derivation. ALL kept int (fed to the period /
# MPOR scalers). No regulatory numerics are hardcoded in this engine module.
# (S13-h; SFT/FCCM margined extension.)
_PACK = resolve("crr", date(2026, 1, 1))
_LIQUIDATION_PERIOD_REPO = _PACK.int_param("liquidation_period_repo").value
_MPOR_FLOOR_REPO_ONLY = _PACK.int_param(
    "mf_margined_floor_days_repo_sft"
).value  # 5, Art. 285(2)(a)
_MPOR_FLOOR_OTHER = _PACK.int_param("mf_margined_floor_days_otc").value  # 10, Art. 285(2)(b)
_MPOR_FLOOR_LARGE_ILLIQ = _PACK.int_param(
    "mf_margined_floor_days_large_or_illiquid"
).value  # 20, Art. 285(3)
_MPOR_DISPUTE_MULT = _PACK.int_param("mf_margined_dispute_multiplier").value  # 2, Art. 285(4)

# MPOR floor F by ``mpor_floor_category`` (keys mirror VALID_MPOR_FLOOR_CATEGORIES
# in data/schemas.py). Values are pack-bound ints (not str literals), so this dict
# is not a regulatory-string collection (arch_check check 6) and its values are
# resolved pack names (arch_check check 5).
_MPOR_FLOOR_BY_CATEGORY: dict[str, int] = {
    "repo_only": _MPOR_FLOOR_REPO_ONLY,
    "other": _MPOR_FLOOR_OTHER,
    "illiquid_or_large": _MPOR_FLOOR_LARGE_ILLIQ,
}

#: Regulatory citation attached to the CCR027 warning.
SFT_COLLATERAL_NOT_RECOGNISED_REG_REF = "CRR / PS1/26 Art. 197, 198, 223(1)"


# =============================================================================
# Public API
# =============================================================================


@cites("CRR Art. 220")
@cites("CRR Art. 223")
@cites("CRR Art. 224")
@cites("CRR Art. 226")
@cites("CRR Art. 271")
@cites("CRR Art. 285")
@cites("PS1/26, paragraph 224")
def sft_bundle_to_exposures(
    raw_sft: RawSFTBundle,
    reporting_date: date,
    rulepack: ResolvedRulepack | None = None,
) -> tuple[pl.LazyFrame, list[CalculationError]]:
    """Shape FCCM SFT EADs into synthetic exposure rows from the lean SFT bundle.

    The sole FCCM entry point (SFT/FCCM separation): consumes the dedicated
    :class:`RawSFTBundle` (``RawDataBundle.sft``). The SFT/derivative
    discrimination lives in the *input bundle* now, not in any in-engine
    ``transaction_type`` split:

    - Every trade row is an SFT (no ``transaction_type`` filter): the whole
      ``raw_sft.trades`` frame is in scope.
    - The netting-set ``counterparty_reference`` is denormalised onto the trade
      row. :func:`apply_sft_netting_gate` first splits every multi-trade set that
      is not under an eligible bilateral master netting agreement into one set
      per trade (Art. 220(1), 220(4)), so after the gate each set names exactly
      one counterparty and the NS-grain counterparty is exact.
    - Collateral is OPTIONAL (``raw_sft.collateral is None`` for an
      uncollateralised SFT, the common case): a missing collateral leaf yields a
      zero collateral term (CVA·(1−HC−HFX) = 0).

    Each emitted synthetic exposure row carries the FCCM provenance:
    ``exposure_reference = "ccr__<netting_set_id>"``, ``risk_type = "CCR_SFT"``,
    ``ccr_method = "fccm_sft"``, ``drawn_amount = E*``, ``ead_ccr = E*``.

    Args:
        raw_sft: The SFT (FCCM) input bundle — every trade row is an SFT with the
            denormalised netting-set counterparty; collateral optional.
        reporting_date: As-of date; written to ``value_date``.
        rulepack: The resolved RUN rulepack supplying the Art. 224 haircut table
            selector (``collateral_haircut_maturity_bands_revised``) and the
            Art. 162 effective-maturity floors / regime gate. ``None`` (direct
            unit / acceptance calls) falls back to the module-level CRR
            ``_PACK``; the stage adapter threads the run pack so production runs
            are regime-correct.

    Returns:
        ``(rows, errors)``: a LazyFrame at (post-gate) netting-set grain — empty
        when the trades bundle is empty — and the CCR027 / CCR028 / CCR029
        diagnostics for the unified error channel.

    References:
        CRR Art. 271(2); Art. 220(1)/(4); Art. 223(1)/(5); Art. 224 Tables 1/3;
        Art. 224(2)(b); Art. 224(4); Art. 226; Art. 285(2)-(5);
        PS1/26 Art. 224(1); PS1/26 Art. 111(2A).
    """
    pack = rulepack if rulepack is not None else _PACK
    # Materialise the firm-scale SFT book once: the netting gate, the per-row
    # HE / HC haircut lookups and the CCR027 diagnostics all read concrete rows
    # (tens to hundreds of trades — far cheaper than a band x CQS x type
    # expression chain in Polars).
    trades_df = raw_sft.trades.sft_trades.collect()
    collateral_df = (
        raw_sft.collateral.sft_collateral.collect() if raw_sft.collateral is not None else None
    )
    trades_df, collateral_df, netting_errors = apply_sft_netting_gate(trades_df, collateral_df)
    rows, collateral_errors = _build_sft_exposure_rows(
        sft_trades_df=trades_df,
        collateral_df=collateral_df,
        reporting_date=reporting_date,
        pack=pack,
    )
    return rows, [*netting_errors, *collateral_errors]


# =============================================================================
# Private helpers
# =============================================================================


@cites("CRR Art. 285")
def _derive_margining_terms(
    is_margined: bool | None,
    remargining_frequency_days: int | None,
    mpor_floor_category: str | None,
    has_margin_dispute_doubling: bool | None,
    mpor_days_override: int | None,
) -> tuple[int, int]:
    """Return ``(T_M, non_daily_N_R)`` for one SFT netting set.

    Selects the applied-haircut holding period T_M and whether the Art. 226
    non-daily revaluation factor √((N_R+T_M−1)/T_M) applies:

    - Branch (a) unmargined: ``(5-BD repo period, real N_R)`` → the Art. 226
      factor applies (driven by ``remargining_frequency_days``; collapses to
      1.0 at daily revaluation). T_M per Art. 224(2)(b).
    - Branch (b) margined: ``(MPOR, 1)`` → the Art. 226 factor is suppressed
      (N_R=1), because the MPOR already encodes the remargin period N.
      MPOR = ``mpor_days_override`` when supplied, else F·mult + N − 1 where F is
      the Art. 285(2)-(3) floor by category and mult = the Art. 285(4) doubling
      multiplier (2) when a margin dispute applies.

    All F values and the dispute multiplier are read from cited pack scalars at
    module load — no regulatory numerics here. The caller derives the terms from
    the first trade of each (post-gate) netting set.

    Args:
        is_margined: True selects the margined branch (b); False/None → (a).
        remargining_frequency_days: N (branch a: N_R; branch b: N). Default 1.
        mpor_floor_category: F selector ('repo_only'/'other'/'illiquid_or_large').
        has_margin_dispute_doubling: True doubles F (Art. 285(4)).
        mpor_days_override: Explicit MPOR (business days); supersedes derivation.

    Returns:
        ``(T_M, non_daily_N_R)`` — both ints in business days / count.
    """
    n = int(remargining_frequency_days) if remargining_frequency_days is not None else 1
    if not is_margined:
        return (_LIQUIDATION_PERIOD_REPO, n)
    if mpor_days_override is not None:
        return (int(mpor_days_override), 1)
    floor = _MPOR_FLOOR_BY_CATEGORY[mpor_floor_category or "repo_only"]
    mult = _MPOR_DISPUTE_MULT if has_margin_dispute_doubling else 1
    return (floor * mult + n - 1, 1)


@cites("CRR Art. 162")
@cites("PS1/26, paragraph 162")
def _derive_ccr_sft_maturity_years(
    *,
    remaining_years: float | None,
    under_mna: bool,
    qualifies_one_day_floor: bool,
    qualifies_mna_intermediate_floor: bool,
    pack: ResolvedRulepack,
) -> float | None:
    """Return the Art. 162 effective maturity M for one SFT netting set, or None.

    The carrier is the FULL M = ``clip(remaining_years, floor, 5.0)`` — the floor
    is a MINIMUM on the remaining maturity (Art. 162(2)(d)/(3)), never a fixed
    replacement value. For a long-dated MNA exposure the floor does not bite and
    M = ``remaining_years``. Returns ``None`` (the date-derived 1-year catch-all,
    Art. 162(2)(f) / PS1/26 162(2A)(f)) when the row is not under a master netting
    agreement or carries no maturity.

    Floor precedence (all sub-1y floors require the MNA precondition):

    - not under an MNA, or ``remaining_years is None`` -> ``None`` (1y catch-all).
    - ``qualifies_one_day_floor`` (the three conjunctive Art. 162(3) conditions —
      daily re-margin AND revaluation AND prompt-liquidation docs) -> the one-day
      (~1/365 y) floor.
    - else the 5BD repo/SFT floor (Art. 162(2)(d) / PS1/26 162(2A)(d)). Under B31
      the intermediate floor additionally requires the 162(2A)(c)/(d) daily
      documentation condition (gated by the
      ``mna_intermediate_floor_requires_daily_condition`` feature); without it the
      row falls to the 1-year catch-all (``None``). Under CRR the floor applies on
      MNA alone (the feature is off).

    Floors / feature are read from the RUN ``pack`` (not the module ``_PACK``) so
    the derivation is regime-correct.

    Args:
        remaining_years: Exact /365 fractional years to maturity, or None.
        under_mna: Art. 162(2) master-netting-agreement precondition.
        qualifies_one_day_floor: All three Art. 162(3) conditions hold.
        qualifies_mna_intermediate_floor: The B31 162(2A)(c)/(d) daily condition.
        pack: The resolved run rulepack supplying the cited maturity floors / gate.

    Returns:
        M as a float, or ``None`` for the date-derived 1-year catch-all.
    """
    if not under_mna or remaining_years is None:
        return None
    cap = 5.0
    if qualifies_one_day_floor:
        floor = float(pack.scalar_param("one_day_maturity_floor_years").value)
    else:
        requires_daily = pack.feature("mna_intermediate_floor_requires_daily_condition")
        intermediate_available = (not requires_daily) or qualifies_mna_intermediate_floor
        if not intermediate_available:
            return None
        floor = float(pack.scalar_param("irb_maturity_floor_repo_sft_years").value)
    return min(max(remaining_years, floor), cap)


def _remaining_years(reporting_date: date, maturity_date: date | None) -> float | None:
    """Exact fractional years from ``reporting_date`` to ``maturity_date``, or None.

    Uses the engine's /365 ordinal day-count (the eager-loop equivalent of
    :func:`rwa_calc.engine.utils.exact_fractional_years_expr`):

        (mat.year − rep.year) + (mat_ordinal − rep_ordinal) / 365

    Returns ``None`` when ``maturity_date`` is null (carrier -> None downstream).
    """
    if maturity_date is None:
        return None
    return (maturity_date.year - reporting_date.year) + (
        maturity_date.timetuple().tm_yday - reporting_date.timetuple().tm_yday
    ) / 365.0


def _build_sft_exposure_rows(
    sft_trades_df: pl.DataFrame,
    collateral_df: pl.DataFrame | None,
    reporting_date: date,
    pack: ResolvedRulepack,
) -> tuple[pl.LazyFrame, list[CalculationError]]:
    """Compute the FCCM E* per netting set and shape the synthetic rows.

    The single home of the Art. 223(5) E* arithmetic, consumed by the
    :func:`sft_bundle_to_exposures` entry point. Kept as a separate core so the
    regulatory math is declared once and the entry point reads as pure input
    plumbing.

    Args:
        sft_trades_df: Post-netting-gate SFT trade rows (materialised by the
            entry point), carrying ``netting_set_id``, ``counterparty_reference``,
            ``notional``, ``currency``, ``maturity_date`` and the three
            Art. 223(5) HE columns.
        collateral_df: Post-netting-gate netting-set-keyed collateral feeding the
            ``CVA·(1−HC−HFX)`` term, or ``None`` for an uncollateralised book.
        reporting_date: As-of date; written to ``value_date``.
        pack: The resolved run rulepack supplying the Art. 224 table selector and
            the Art. 162 effective-maturity floors / regime gate.

    Returns:
        ``(rows, errors)`` — the NS-grain LazyFrame with the FCCM provenance
        columns, and one CCR027 per collateral row not recognised.

    References:
        CRR Art. 223(1)/(5); Art. 224 Tables 1/3; Art. 224(2)(b); Art. 224(4);
        Art. 226; Art. 285(2)-(5); PS1/26 Art. 224(1).
    """
    # PS1/26 Art. 224(1) Tables 1/3 (Basel 3.1) vs CRR Art. 224 Table 1/3: the
    # cited Feature selects the regime's table — values AND maturity bands —
    # exactly as the lending-side CRM does (engine/crm/collateral.py).
    revised_table = bool(pack.feature("collateral_haircut_maturity_bands_revised"))

    # ---- 0) Per-NS (T_M, N_R) margining terms --------------------------------
    # The Art. 285 margining inputs are denormalised onto the TRADE row. Derive
    # the applied holding period T_M and the Art. 226 non-daily revaluation count
    # N_R per netting set from the first trade of each set — exact on the split
    # (single-trade) sets the netting gate produces, and on a netted set the
    # documented first-trade reading. The five margining columns are backfilled
    # to their schema defaults by the standard loader seal (``seal_lenient``), so
    # ``row.get(col, default)`` reads the value when present and the
    # conservative default otherwise.
    # The per-NS Art. 162 effective-maturity carrier (``ccr_effective_maturity``)
    # is derived alongside the margining terms — both off the same first-trade row
    # per NS. The three Art. 162 input flags (``under_master_netting_agreement`` /
    # ``qualifies_one_day_maturity_floor`` / ``qualifies_mna_intermediate_floor``)
    # default conservatively to False (absent flag never unlocks a sub-1y floor),
    # and a null ``maturity_date`` yields a None carrier (date-derived 1y catch-all
    # downstream).
    ns_terms: dict[str, tuple[int, int]] = {}
    ns_maturity: dict[str, float | None] = {}
    # Per-NS own-estimate LGD carrier for A-IRB routing (P1.215), collapsed to NS
    # grain via the MAX across every trade in the set — deterministic AND
    # conservative (the highest modelled LGD drives the largest capital
    # requirement), mirroring the ``.max()`` collapse in the SA-CCR pipeline
    # adapter. This scan runs for every row (outside the first-trade guard that
    # gates the margining terms / effective maturity below) so a multi-trade NS
    # with heterogeneous modelled LGDs collapses order-independently. Null
    # carrier => the synthetic row falls to SA / FIRB downstream.
    ns_modelled_lgd: dict[str, float | None] = {}
    for row in sft_trades_df.iter_rows(named=True):
        ns_id = row["netting_set_id"]
        trade_lgd = row.get("ccr_modelled_lgd")
        if trade_lgd is not None:
            prior = ns_modelled_lgd.get(ns_id)
            ns_modelled_lgd[ns_id] = trade_lgd if prior is None else max(prior, trade_lgd)
        else:
            ns_modelled_lgd.setdefault(ns_id, None)
        if ns_id in ns_terms:
            continue
        ns_terms[ns_id] = _derive_margining_terms(
            is_margined=row.get("is_margined", False),
            remargining_frequency_days=row.get("remargining_frequency_days", 1),
            mpor_floor_category=row.get("mpor_floor_category", "repo_only"),
            has_margin_dispute_doubling=row.get("has_margin_dispute_doubling", False),
            mpor_days_override=row.get("mpor_days_override", None),
        )
        ns_maturity[ns_id] = _derive_ccr_sft_maturity_years(
            remaining_years=_remaining_years(reporting_date, row.get("maturity_date")),
            under_mna=bool(row.get("under_master_netting_agreement", False)),
            qualifies_one_day_floor=bool(row.get("qualifies_one_day_maturity_floor", False)),
            qualifies_mna_intermediate_floor=bool(
                row.get("qualifies_mna_intermediate_floor", False)
            ),
            pack=pack,
        )

    # ---- 1) Per-trade E·(1+HE) -------------------------------------------------
    # HE is per-row (depends on the security being lent / sold).
    he_values: list[float] = []
    for row in sft_trades_df.iter_rows(named=True):
        t_m, n_r = ns_terms[row["netting_set_id"]]
        he_values.append(
            _compute_exposure_haircut(
                security_type=row.get("exposure_collateral_type"),
                cqs=row.get("exposure_security_cqs"),
                residual_maturity_years=row.get("exposure_security_residual_maturity_years"),
                holding_period_days=t_m,
                revaluation_freq_days=n_r,
                revised_table=revised_table,
            )
        )
    sft_trades_with_he = sft_trades_df.with_columns(
        pl.Series("_he", he_values, dtype=pl.Float64),
    ).with_columns(
        (pl.col("notional").fill_null(0.0) * (1.0 + pl.col("_he"))).alias("_e_times_one_plus_he"),
    )

    # ---- 2) Per-NS sum (a netted set sums every trade) -------------------------
    ns_e_grossed = (
        sft_trades_with_he.group_by("netting_set_id", maintain_order=True)
        .agg(
            [
                pl.col("_e_times_one_plus_he").sum().alias("_e_grossed"),
                pl.col("currency").first().alias("_trade_currency"),
                pl.col("maturity_date").max().alias("_trade_max_maturity"),
                # Exact: after the netting gate every set names one counterparty.
                pl.col("counterparty_reference").first(),
            ]
        )
        .lazy()
    )

    # ---- 3) Per-NS collateral CVA·(1−HC−HFX) ---------------------------------
    errors: list[CalculationError] = []
    if collateral_df is None or collateral_df.is_empty():
        cva_per_ns: pl.LazyFrame = ns_e_grossed.select(
            pl.col("netting_set_id"),
            pl.lit(0.0).alias("_cva_net"),
        )
    else:
        # Join trade currency onto the collateral frame for the same-currency
        # HFX shortcut (Art. 224 Table 4: HFX=0 when collateral currency equals
        # exposure currency).
        ns_currency_df = sft_trades_with_he.group_by("netting_set_id").agg(
            pl.col("currency").first().alias("_trade_currency"),
        )
        coll_with_ccy = collateral_df.join(ns_currency_df, on="netting_set_id", how="left")
        cva_values: list[float] = []
        for row in coll_with_ccy.iter_rows(named=True):
            terms = ns_terms.get(row["netting_set_id"])
            if terms is None:
                # Keyed to no SFT trade's netting set: there is no exposure for it
                # to reduce. Named (CCR027) rather than silently dropped.
                errors.append(_collateral_not_recognised_error(row, orphan=True))
                cva_values.append(0.0)
                continue
            t_m, n_r = terms
            contribution = _compute_collateral_cva_contribution(
                collateral_type=row.get("collateral_type"),
                market_value=row.get("market_value") or 0.0,
                cqs=row.get("issuer_cqs"),
                residual_maturity_years=row.get("residual_maturity_years"),
                collateral_currency=row.get("currency"),
                exposure_currency=row.get("_trade_currency"),
                holding_period_days=t_m,
                revaluation_freq_days=n_r,
                revised_table=revised_table,
            )
            if contribution is None:
                errors.append(_collateral_not_recognised_error(row))
                contribution = 0.0
            cva_values.append(contribution)
        cva_per_ns = (
            coll_with_ccy.with_columns(pl.Series("_cva_contrib", cva_values, dtype=pl.Float64))
            .group_by("netting_set_id")
            .agg(pl.col("_cva_contrib").sum().alias("_cva_net"))
            .lazy()
        )

    # ---- 4) Compose NS-grain frame and compute E* ----------------------------
    sft_ns_ids = sft_trades_df["netting_set_id"].unique().to_list()
    # NS-grain Art. 162 effective-maturity carrier. Built from the per-NS
    # ``ns_maturity`` map as a Series with explicit None -> null (the check-11
    # ``fill_null`` ratchet pattern), joined onto the NS frame so a None carrier
    # surfaces as a typed null on the synthetic row (date-derived 1y catch-all
    # downstream).
    # Force the join-key dtype to String: an empty SFT book (zero trades) yields
    # an empty ``sft_ns_ids`` list, from which Polars would infer a Null-typed
    # ``netting_set_id`` column and fail the str-key join (the empty-book
    # pipeline-abort regression).
    ns_maturity_lf = pl.DataFrame(
        {
            "netting_set_id": pl.Series("netting_set_id", sft_ns_ids, dtype=pl.String),
            "ccr_effective_maturity": pl.Series(
                "ccr_effective_maturity",
                [ns_maturity.get(ns_id) for ns_id in sft_ns_ids],
                dtype=pl.Float64,
            ),
            # Per-NS A-IRB own-estimate LGD carrier (P1.215), joined onto the
            # synthetic row alongside the effective-maturity carrier.
            "ccr_modelled_lgd": pl.Series(
                "ccr_modelled_lgd",
                [ns_modelled_lgd.get(ns_id) for ns_id in sft_ns_ids],
                dtype=pl.Float64,
            ),
        }
    ).lazy()
    ns_with_ead = (
        ns_e_grossed.join(cva_per_ns, on="netting_set_id", how="left")
        .join(ns_maturity_lf, on="netting_set_id", how="left")
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
        # Reconciliation base: keep the ``ccr__`` namespace (an SFT netting set
        # has no legacy per-exposure equivalent; a bare id could collide with a
        # loan reference on a base-grain reconciliation key).
        pl.concat_str([pl.lit("ccr__"), pl.col("netting_set_id")]).alias(
            "source_exposure_reference"
        ),
        pl.lit("ccr_netting_set").alias("exposure_type"),
        pl.col("counterparty_reference"),
        pl.lit(reporting_date).alias("value_date"),
        pl.col("_trade_max_maturity").alias("maturity_date"),
        pl.col("_trade_currency").alias("currency"),
        # Denomination currency — see the twin in ``engine/ccr/pipeline_adapter``.
        # The FX converter runs ahead of this stage, so an unstamped synthetic row
        # inherits ``original_currency`` as a null and every
        # ``denomination_currency_expr`` consumer goes indeterminate on it. These
        # rows never pass the converter, so the trade currency IS the denomination.
        pl.col("_trade_currency").alias("original_currency"),
        pl.col("ead_ccr").alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.lit("senior").alias("seniority"),
        pl.lit("CCR_SFT").alias("risk_type"),
        pl.col("netting_set_id").alias("source_netting_set_id"),
        pl.lit("fccm_sft").alias("ccr_method"),
        pl.col("ead_ccr"),
        # Art. 162 effective-maturity carrier for IRB routing (null off the MNA
        # carve-out — date-derived 1y catch-all applies downstream).
        pl.col("ccr_effective_maturity"),
        # Art. 143 own-estimate LGD carrier for A-IRB routing (P1.215; null =>
        # SA / FIRB downstream).
        pl.col("ccr_modelled_lgd"),
    ]
    # Drop helper "_*" columns from the public projection.
    return ns_with_ead.select(select_exprs), errors


def _lookup_haircut_unscaled(
    lookup_type: str,
    cqs: int | None,
    residual_maturity_years: float | None,
    *,
    revised_table: bool,
) -> float | None:
    """Look up the 10-BD base supervisory haircut per Art. 224 Tables 1/3.

    ``revised_table`` selects the PS1/26 Art. 224 table (five maturity bands)
    over the CRR one. Returns ``None`` when the security is ineligible under
    Art. 197 (e.g. an unrated corporate bond), distinguishing that from a
    legitimately-zero haircut (cash). The holding-period scaling is applied by
    the caller via :func:`scale_haircut_for_liquidation_period` (Art. 224(2)) so
    that the SFT EAD formula sees the un-rounded ``H_10 × √(T_M/10)`` value (the
    table-level lookup helper rounds to 6 decimals at the scaled step, which
    would exceed the 1 ppm tolerance pinned by the CCR-A12 golden after net of
    collateral).
    """
    base = lookup_collateral_haircut(
        collateral_type=lookup_type,
        cqs=int(cqs) if cqs is not None else None,
        residual_maturity_years=float(residual_maturity_years)
        if residual_maturity_years is not None
        else None,
        is_basel_3_1=revised_table,
        liquidation_period_days=10,  # un-scaled base; we apply scaling below
    )
    return float(base) if base is not None else None


@cites("CRR Art. 224")
@cites("PS1/26, paragraph 224")
def _exposure_haircut_unscaled(
    security_type: str,
    cqs: int | None,
    residual_maturity_years: float | None,
    *,
    revised_table: bool,
) -> float:
    """10-BD base HE for the security lent / sold, Art. 224(1) and 224(4).

    An eligible security (a type in ``SFT_FCCM_HAIRCUT_LOOKUP_TYPES`` that also
    passes the Art. 197 CQS test) takes its Table 1/3 value. Anything else is a
    "non-eligible security or commodity lent or sold" and takes the Art. 224(4)
    volatility adjustment — "the same volatility adjustment as ... equities
    which are not equities included in a main index but are listed on a
    recognised exchange" (PS1/26 Art. 224(4); CRR Art. 224(4) likewise). The
    Art. 224(4) value is applied as a FLOOR on whatever the lending-side lookup
    returns for the raw string, so a type the engine cannot identify as a
    security at all (``other_physical``, an unknown string) keeps its higher
    40% fall-through rather than being lowered.
    """
    lookup_type = SFT_FCCM_HAIRCUT_LOOKUP_TYPES.get(security_type.lower())
    if lookup_type is not None:
        eligible = _lookup_haircut_unscaled(
            lookup_type, cqs, residual_maturity_years, revised_table=revised_table
        )
        if eligible is not None:
            return eligible
    non_eligible = _lookup_haircut_unscaled(
        "equity", None, None, revised_table=revised_table
    )  # Art. 224(4): Table 3 "other equities ... listed on a recognised exchange"
    fall_through = (
        _lookup_haircut_unscaled(
            security_type, cqs, residual_maturity_years, revised_table=revised_table
        )
        if lookup_type is None
        else None
    )
    return max(fall_through or 0.0, non_eligible or 0.0)


def _compute_exposure_haircut(
    security_type: str | None,
    cqs: int | None,
    residual_maturity_years: float | None,
    holding_period_days: int,
    revaluation_freq_days: int,
    *,
    revised_table: bool,
) -> float:
    """Compute HE for the exposure-side security per Art. 224, scaled to the
    holding period ``T_M`` (Art. 224(2)) and the Art. 226 non-daily factor.

    H_E = H_10 × √(T_M/10) × √((N_R+T_M−1)/T_M). The first two factors are
    :func:`scale_haircut_for_liquidation_period`; the third is
    :func:`scale_haircut_for_non_daily_revaluation` (identity when N_R=1, e.g.
    the margined branch which sets N_R=1, or daily unmargined revaluation).

    Returns 0.0 when ``security_type`` is None: per ``SFT_TRADE_SCHEMA`` a null
    exposure-side type means cash lent (HE = 0, Art. 224 Table 3 cash).
    """
    if security_type is None:
        return 0.0
    base = _exposure_haircut_unscaled(
        security_type, cqs, residual_maturity_years, revised_table=revised_table
    )
    if base == 0.0:
        return 0.0
    scaled = scale_haircut_for_liquidation_period(base, holding_period_days)
    return scale_haircut_for_non_daily_revaluation(
        scaled, revaluation_freq_days, holding_period_days
    )


def _compute_collateral_cva_contribution(
    collateral_type: str | None,
    market_value: float,
    cqs: int | None,
    residual_maturity_years: float | None,
    collateral_currency: str | None,
    exposure_currency: str | None,
    holding_period_days: int,
    revaluation_freq_days: int,
    *,
    revised_table: bool,
) -> float | None:
    """Compute one collateral row's contribution to ``CVA·(1−HC−HFX)``.

    Returns ``None`` when the row is not recognised — a null type, a type
    outside ``SFT_FCCM_HAIRCUT_LOOKUP_TYPES`` (Art. 223(1): volatility
    adjustments value FINANCIAL collateral; real estate, receivables and other
    physical collateral are not Art. 197/198 items), or a debt security failing
    the Art. 197(1)(b)-(d) CQS test. The caller records CCR027 and recognises
    nothing.

    HC and HFX are sourced from Art. 224 Tables 1/3/4 (unscaled lookup), scaled
    to the holding period ``T_M`` (Art. 224(2)) and then by the Art. 226
    non-daily revaluation factor √((N_R+T_M−1)/T_M) — applied independently to
    HC and HFX (identity when N_R=1, e.g. the margined branch or daily
    revaluation). HFX is 0% when the collateral and exposure currencies match
    (Art. 224 Table 4).
    """
    if collateral_type is None:
        return None
    lookup_type = SFT_FCCM_HAIRCUT_LOOKUP_TYPES.get(collateral_type.lower())
    if lookup_type is None:
        return None
    base = _lookup_haircut_unscaled(
        lookup_type, cqs, residual_maturity_years, revised_table=revised_table
    )
    if base is None:
        return None
    hc = scale_haircut_for_non_daily_revaluation(
        scale_haircut_for_liquidation_period(base, holding_period_days),
        revaluation_freq_days,
        holding_period_days,
    )
    same_currency = (
        collateral_currency is not None
        and exposure_currency is not None
        and collateral_currency.upper() == exposure_currency.upper()
    )
    if same_currency:
        hfx = 0.0
    else:
        hfx = scale_haircut_for_non_daily_revaluation(
            scale_haircut_for_liquidation_period(float(FX_HAIRCUT), holding_period_days),
            revaluation_freq_days,
            holding_period_days,
        )
    return float(market_value) * (1.0 - hc - hfx)


def _collateral_not_recognised_error(
    row: dict[str, Any], *, orphan: bool = False
) -> CalculationError:
    """CCR027 for one SFT collateral row that contributes nothing to E*."""
    collateral_type = row.get("collateral_type")
    if orphan:
        reason = "is keyed to a netting set that holds no SFT trade"
    elif collateral_type is None or collateral_type.lower() not in SFT_FCCM_HAIRCUT_LOOKUP_TYPES:
        reason = "is not a financial-collateral type the SFT path prices from Art. 224 Tables 1/3"
    else:
        reason = (
            f"fails the Art. 197(1)(b)-(d) credit-quality test (issuer_cqs={row.get('issuer_cqs')})"
        )
    return CalculationError(
        code=ERROR_SFT_COLLATERAL_NOT_RECOGNISED,
        message=(
            f"SFT collateral {row.get('sft_collateral_reference')} on netting set "
            f"{row.get('netting_set_id')} (collateral_type={collateral_type!r}) {reason}; "
            "it is not recognised in E* (Art. 223(1) values financial collateral only)."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CRM,
        regulatory_reference=SFT_COLLATERAL_NOT_RECOGNISED_REG_REF,
        field_name="collateral_type",
        expected_value="eligible financial collateral (Art. 197 / 198)",
        actual_value=str(collateral_type),
    )
