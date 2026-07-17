"""
SA-CCR pipeline adapter: netting-set-grain CCR EAD as synthetic exposure rows.

Pipeline position:
    HierarchyResolver -> [CCR pipeline adapter] -> Classifier
        -> CRMProcessor -> SA/IRB/Slotting Calculators

Key responsibilities:
- Chain the existing SA-CCR engine functions
  (adjusted notional, supervisory delta, maturity factor, hedging set,
  asset-class add-on, PFE multiplier, EAD) over a ``RawCCRBundle`` to
  produce one ``ead_ccr`` value per netting set.
- Shape each netting-set row into a synthetic exposure row compatible
  with the unified ``RAW_EXPOSURE_SCHEMA`` (extended with provenance
  columns ``source_netting_set_id`` and ``ccr_method``) so the rest of
  the pipeline (Classifier -> CRM -> SA calculator -> Aggregator) can
  consume the CCR EAD without any CCR-aware special-cases downstream.
- Stay LazyFrame-first: the netting-set frame and the synthetic-exposure
  frame returned by ``ccr_rows_to_exposures`` are both ``pl.LazyFrame``.

References:
- CRR Art. 271: scope (one EAD row per netting set / counterparty pair)
- CRR Art. 272(4): netting-set definition + legal-enforceability fallback
- CRR Art. 274(2): EAD = alpha * (RC + PFE)
- CRR Art. 275(1): replacement cost (unmargined)
- CRR Art. 277(1)-(2): hedging-set and IR maturity-bucket partition
- CRR Art. 277a(1)(a): intra-asset-class add-on aggregation
- CRR Art. 278(1)-(3): PFE multiplier + add-on
- CRR Art. 279a-c: supervisory delta / adjusted notional / maturity factor
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CCRConfig
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import CCR_ALPHA_CARVE_OUT_COUNTERPARTY_TYPES, NETTING_SET_SCHEMA
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.ccr.adjusted_notional import (
    compute_adjusted_notional_commodity,
    compute_adjusted_notional_credit,
    compute_adjusted_notional_equity,
    compute_adjusted_notional_fx,
    compute_adjusted_notional_ir,
)
from rwa_calc.engine.ccr.hedging_sets import assign_hedging_set
from rwa_calc.engine.ccr.maturity_factor import (
    compute_maturity_factor_margined,
    compute_maturity_factor_unmargined,
)
from rwa_calc.engine.ccr.pfe import compute_addon_per_asset_class, compute_pfe
from rwa_calc.engine.ccr.rc import compute_rc_margined, compute_rc_unmargined
from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_option
from rwa_calc.rulebook.compile import lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# SA-CCR supervisory alpha resolved from the rulepack once at module load (CRR
# Art. 274(2); regime-invariant, resolved against "crr"). Closes the prior
# dual-maintenance with data/tables/sa_ccr_factors.py.
_PACK = resolve("crr", date(2026, 1, 1))
_SA_CCR_ALPHA = scalar_value(_PACK.scalar_param("sa_ccr_alpha"))
_SA_CCR_ALPHA_CARVE_OUT = scalar_value(_PACK.scalar_param("sa_ccr_alpha_carve_out"))

# PRA PS1/26 Art. 274(2A) transitional alpha add-on phase fractions by reporting
# year (Basel 3.1 only → resolved from the b31 pack). Years absent resolve to 0.
_B31_PACK = resolve("b31", date(2027, 1, 1))
_TRANSITIONAL_ADDON_PHASE = lookup_float_map(_B31_PACK.lookup("sa_ccr_transitional_addon_phase"))

# ``"sft"`` is the TRADE_SCHEMA.transaction_type token for securities-financing
# transactions (CRR Art. 220(1)(a)). After the SFT/FCCM separation (Phase 6) the
# SA-CCR derivative chain in this module is derivatives-only: SFT EAD is computed
# by the peer ``sft_fccm`` stage from ``RawDataBundle.sft``. Any ``"sft"`` row
# that still arrives in ``RawDataBundle.ccr`` is mis-placed input — the
# ``partition_out_sft_rows`` guard below excludes it from the Art. 274 chain and
# raises a data-quality ``CalculationError`` rather than mis-pricing it as a
# derivative. Declared locally as a literal routing token (not a regulatory
# scalar; arch_check check 6 allows the value, mirroring the prior
# ``engine/sft/fccm.py::SFT_TRANSACTION_TYPE``).
_SFT_TRANSACTION_TYPE: str = "sft"

#: Error code emitted by :func:`partition_out_sft_rows` when an SFT row survives
#: in ``RawDataBundle.ccr`` after the Phase 6 source flip.
CCR_SFT_IN_DERIVATIVE_INPUT_ERROR_CODE = "CCR020"

#: Regulatory citation attached to the CCR020 data-quality error.
CCR_SFT_IN_DERIVATIVE_INPUT_REG_REF = "CRR Art. 271(2); Art. 220-223"


# =============================================================================
# Public API
# =============================================================================


def ccr_rows_to_exposures(
    raw_ccr: RawCCRBundle,
    config_ccr: CCRConfig,
    reporting_date: date,
    *,
    base_currency: str = "GBP",
    fx_rates: pl.LazyFrame | None = None,
    counterparties: pl.LazyFrame | None = None,
    is_basel_3_1: bool = False,
) -> pl.LazyFrame:
    """Shape SA-CCR netting-set EADs into synthetic exposure rows.

    Drives the full SA-CCR Art. 274 chain over the legally-enforceable trades
    and netting sets in ``raw_ccr`` and emits one row per netting set with
    columns compatible with the unified ``RAW_EXPOSURE_SCHEMA``.

    DERIVATIVES-ONLY (SFT/FCCM separation, Phase 6). SFT EAD (CRR Art. 271(2),
    Art. 220-223 FCCM) is now computed by the peer ``sft_fccm`` stage from the
    dedicated ``RawDataBundle.sft`` input — never here. Callers are expected to
    pass a derivatives-only bundle; the stage applies :func:`partition_out_sft_rows`
    first to strip (and flag) any mis-placed ``transaction_type == "sft"`` rows so
    they cannot be mis-priced through the Art. 274 chain.

    Each emitted synthetic exposure row carries the columns:

        exposure_reference    = "ccr__<netting_set_id>"
        exposure_type         = "ccr_netting_set"
        counterparty_reference= from NETTING_SET_SCHEMA
        risk_type             = "CCR_DERIVATIVE"
        drawn_amount          = ead_ccr  (alpha * (RC + PFE))
        interest              = 0.0
        undrawn_amount        = 0.0
        nominal_amount        = 0.0
        currency              = first trade currency in the NS
        value_date            = config.reporting_date
        maturity_date         = max(trade maturity in the NS)
        seniority             = "senior"   (conservative default)
        source_netting_set_id = <netting_set_id>
        ccr_method            = "sa_ccr"
        addon_aggregate       = per-NS asset-class add-on aggregate
        addon_by_asset_class  = Struct{interest_rate, fx, credit, equity,
                                       commodity} per-class add-on breakdown
        pfe_multiplier        = Art. 278(3) multiplier
        pfe_addon             = Art. 278(1) PFE
        rc_unmargined         = Art. 275(1) replacement cost
        rc_margined           = Art. 275(2) replacement cost (null if unmargined)
        rc                    = unified RC (margined where applicable) feeding EAD
        ead_ccr               = Art. 274(2) EAD at alpha

    The downstream concat in the orchestrator uses ``how="diagonal_relaxed"``
    so any other ``RAW_EXPOSURE_SCHEMA`` columns absent here are filled with
    nulls; the CCR row then flows through Classifier / CRM / SA Calculator
    as a vanilla unsecured corporate-style exposure where drawn_amount is
    already the post-CCR EAD.

    Args:
        raw_ccr: CCR bundle whose legal-enforceability gate has already been
            applied upstream (non-enforceable netting sets are split into
            single-trade NSes per Art. 272(4)).
        config_ccr: CCR configuration (controls alpha for compute_pfe).
        reporting_date: As-of date for the calculation; used to compute
            ``years_to_maturity`` and ``adjusted_notional`` per Art. 279b
            and is written to the synthetic exposure row's ``value_date``.
        base_currency: Reporting currency for FX adjusted notional per
            Art. 279b(1)(b); typically ``CalculationConfig.base_currency``.
            Used only when ``fx_rates`` is supplied and the trade book contains
            ``asset_class == "fx"`` rows. Defaults to ``"GBP"``.
        fx_rates: Optional FX-rates LazyFrame conforming to ``FX_RATES_SCHEMA``
            (``currency_from``, ``currency_to``, ``rate``). When None the FX
            adjusted-notional branch is skipped — FX trades will have null
            ``adjusted_notional`` and therefore no PFE contribution, matching
            the pre-P8.9 behaviour for firms with no derivatives FX book.
        counterparties: Optional counterparty LazyFrame carrying
            ``counterparty_reference`` and ``counterparty_type`` (COUNTERPARTY_SCHEMA).
            Joined onto the netting-set frame to select the per-row supervisory
            alpha (CRR Art. 274(2) second sub-paragraph): 1.0 for non-financial /
            pension-scheme counterparties, 1.4 otherwise. When None — or when the
            ``counterparty_type`` column is absent — every netting set keeps the
            default alpha = 1.4, preserving pre-P8.28 behaviour.
        is_basel_3_1: Framework flag gating the PRA PS1/26 Art. 274(2A)
            transitional alpha add-on. The add-on is Basel 3.1 only — under CRR
            (the default ``False``) it never fires regardless of the reporting
            date or the ``is_legacy_cva_exempt`` trade flag.

    Returns:
        LazyFrame at netting-set grain with one synthetic exposure row per
        netting set in ``raw_ccr``. Empty (zero-row) frame when the trades
        bundle is empty.

    References:
        CRR Art. 271; CRR Art. 274; CRR Art. 277-279c; CRR Art. 278;
        PRA PS1/26 Art. 274(2A).

    The optional ``counterparties`` frame supplies the per-netting-set
    supervisory-alpha discriminator: its ``counterparty_type`` column is joined
    onto the netting-set frame (keyed on ``counterparty_reference``) and reduced
    to an ``alpha_applied`` scalar per CRR Art. 274(2) second sub-paragraph
    before :func:`compute_pfe` consumes it. Absent / null ``counterparty_type``
    defaults to alpha = 1.4 (financial).

    When ``is_basel_3_1`` is True the trade-level ``is_legacy_cva_exempt`` flag
    (TRADE_SCHEMA) is collapsed to netting-set grain via ``any()`` and — for
    netting sets that also carry the α=1.0 carve-out and a non-zero phase
    fraction for ``reporting_date.year`` — a PRA PS1/26 Art. 274(2A)
    transitional add-on is computed and folded into ``ead_ccr``.
    """
    trades_lf = raw_ccr.trades.trades
    netting_sets_lf = raw_ccr.netting_sets.netting_sets

    # 1) Enrich trade-level frame with residual-maturity measures, then chain the
    #    per-trade SA-CCR components in regulatory order. Two distinct measures:
    #    - ``years_to_maturity`` (calendar days / 365.25): feeds the Art. 277(2)
    #      IR maturity buckets (1y / 5y thresholds), a calendar-based partition.
    #    - ``business_days_to_maturity`` (Mon-Fri business-day count): feeds the
    #      Art. 279c(1) unmargined maturity factor MF = sqrt(min(BD, 250) / 250),
    #      on the same 250-business-day-year basis as the margined MF (Art. 279c(2)).
    trades_enriched = trades_lf.with_columns(
        ((pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25).alias(
            "years_to_maturity"
        ),
        pl.business_day_count(pl.lit(reporting_date), pl.col("maturity_date")).alias(
            "business_days_to_maturity"
        ),
    )
    trades_enriched = compute_adjusted_notional_ir(trades_enriched, reporting_date)
    # FX adjusted notional per Art. 279b(1)(b) — overlays the FX branch on top
    # of the IR output via coalesce so non-FX rows pass through unchanged.
    if fx_rates is not None:
        trades_enriched = compute_adjusted_notional_fx(trades_enriched, base_currency, fx_rates)
    # Credit adjusted notional per Art. 279b(1)(a) — shares the IR supervisory-
    # duration kernel and overlays via coalesce; no gate needed (no-op for
    # non-credit rows).
    trades_enriched = compute_adjusted_notional_credit(trades_enriched, reporting_date)
    # Equity adjusted notional per Art. 279b(1)(c) — overlays the equity branch
    # on top of any prior IR/FX/credit result via coalesce; no-op for non-equity rows.
    trades_enriched = compute_adjusted_notional_equity(trades_enriched)
    # Commodity adjusted notional per Art. 279b(1)(c) — coalesce-safe overlay,
    # no-op for non-commodity rows.
    trades_enriched = compute_adjusted_notional_commodity(trades_enriched)
    # Supervisory delta per CRR Art. 279a: the option branch applies the
    # Black-Scholes Phi(d1) formula (Art. 279a(2)) when a trade carries both
    # ``option_strike`` and ``option_underlying_price`` and falls back to the
    # linear +/- 1 delta (Art. 279a(1)) for non-option rows. This single call
    # therefore covers both directional and option trades in the book.
    trades_enriched = compute_supervisory_delta_option(trades_enriched)

    # Denormalise the Art. 285 MPOR-cascade inputs onto each trade so the
    # margined maturity factor (Art. 279c(2)) can be computed at trade grain.
    # ``is_margined``, ``number_of_trades``, ``has_illiquid`` and
    # ``mpor_days_input`` ride on the netting set (NETTING_SET_SCHEMA); the
    # ``remargining_frequency_days`` / ``dispute_count_qtr`` CSA terms ride on
    # the margin agreement (MARGIN_AGREEMENT_SCHEMA) and are joined via the
    # netting set's ``margin_agreement_id``. ``remargining_frequency_days`` is a
    # business-day count (Art. 285(5)) — deliberately NOT conflated with the
    # calendar-day ``years_to_maturity`` derived above.
    trades_enriched = _attach_mpor_cascade_inputs(
        trades_enriched, netting_sets_lf, raw_ccr.margin_agreements.margin_agreements
    )

    # Maturity factor (Art. 279c). The unmargined fn writes the bare
    # ``maturity_factor``; rename it to ``maturity_factor_unmargined`` so the
    # margined fn (which writes ``maturity_factor_margined``, gated null on
    # unmargined rows) does not clobber it. Coalesce both into the unified
    # ``maturity_factor`` BEFORE the add-on consumes it (mirrors the
    # rc_margined / rc_unmargined coalesce below).
    trades_enriched = compute_maturity_factor_unmargined(trades_enriched).rename(
        {"maturity_factor": "maturity_factor_unmargined"}
    )
    trades_enriched = compute_maturity_factor_margined(trades_enriched)
    trades_enriched = assign_hedging_set(trades_enriched)
    trades_enriched = trades_enriched.with_columns(
        pl.coalesce(pl.col("maturity_factor_margined"), pl.col("maturity_factor_unmargined")).alias(
            "maturity_factor"
        )
    )

    # 2) Per-(NS, asset_class) add-on, then aggregate to per-NS sum.
    addon_per_class = compute_addon_per_asset_class(trades_enriched)
    addon_per_ns = addon_per_class.group_by("netting_set_id").agg(
        pl.col("asset_class_addon").fill_null(0.0).sum().alias("addon_aggregate")
    )
    # 2b) Per-NS struct breakdown of the per-asset-class add-on so the
    #     synthetic exposure row carries an auditable reconciliation of
    #     ``addon_aggregate`` to its five Art. 277(1) asset-class components.
    #     Missing asset classes in a netting set become 0.0 in the struct so
    #     ``sum(struct) == addon_aggregate`` holds for every NS row.
    #     LazyFrame-first: pivot via a group_by + conditional-sum over the
    #     five fixed asset-class labels rather than the eager-only pl.pivot.
    asset_class_struct_fields = ["interest_rate", "fx", "credit", "equity", "commodity"]
    addon_by_class_per_ns = (
        addon_per_class.group_by("netting_set_id")
        .agg(
            [
                pl.when(pl.col("asset_class") == asset_class)
                .then(pl.col("asset_class_addon"))
                .otherwise(None)
                .sum()
                .fill_null(0.0)
                .alias(asset_class)
                for asset_class in asset_class_struct_fields
            ]
        )
        .select(
            [
                pl.col("netting_set_id"),
                pl.struct([pl.col(c) for c in asset_class_struct_fields]).alias(
                    "addon_by_asset_class"
                ),
            ]
        )
    )

    # 3) Per-NS v_net (sum of mtm_value over trades) and trade-level metadata
    #    needed for synthetic-exposure rows (currency, max maturity).
    #    The trade-level ``is_client_cleared`` flag (CRR Art. 305(2)) is
    #    collapsed to netting-set grain via ``any()`` so the synthetic row can
    #    surface ``cp_is_ccp_client_cleared`` for the Art. 306(1)(c) 4% pin in
    #    the SA calculator. Absent column -> all-False aggregate.
    trade_cols = trades_lf.collect_schema().names()
    client_cleared_agg = (
        pl.col("is_client_cleared").fill_null(False).any().alias("_ns_is_client_cleared")
        if "is_client_cleared" in trade_cols
        else pl.lit(False).alias("_ns_is_client_cleared")
    )
    # PRA PS1/26 Art. 274(2A): collapse the trade-level legacy CVA-exemption
    # flag to netting-set grain via ``any()`` (a netting set qualifies if ANY
    # of its trades is legacy CVA-exempt), exactly as ``is_client_cleared`` is
    # collapsed above. Absent column (Python-bundle path / older fixtures) ->
    # all-False aggregate so the add-on never fires.
    legacy_cva_exempt_agg = (
        pl.col("is_legacy_cva_exempt").fill_null(False).any().alias("_ns_is_legacy_cva_exempt")
        if "is_legacy_cva_exempt" in trade_cols
        else pl.lit(False).alias("_ns_is_legacy_cva_exempt")
    )
    # Own-estimate LGD carrier for A-IRB routing (P1.215), collapsed to NS grain
    # via ``.max()`` — deterministic AND conservative. A group_by has no stable
    # row order, so ``.first()`` would pick an order-nondeterministic value across
    # a multi-trade netting set with heterogeneous modelled LGDs; ``.max()`` is
    # order-independent and selects the highest LGD — the most conservative
    # capital input (a higher LGD drives a larger K / RWA). Ensure the carrier as
    # a typed null first (older fixtures / Python bundle path may omit it) — the
    # ensure_columns pattern avoids a presence-guard ratchet site.
    trades_lf = ensure_columns(
        trades_lf, {"ccr_modelled_lgd": ColumnSpec(pl.Float64, default=None, required=False)}
    )
    ns_trade_aggregates = trades_lf.group_by("netting_set_id").agg(
        [
            pl.col("mtm_value").fill_null(0.0).sum().alias("v_net"),
            pl.col("currency").first().alias("_trade_currency"),
            pl.col("maturity_date").max().alias("_trade_max_maturity"),
            client_cleared_agg,
            legacy_cva_exempt_agg,
            pl.col("ccr_modelled_lgd").max().alias("ccr_modelled_lgd"),
        ]
    )

    # 4) CCR collateral: per-NS c_net. CCR-A1 has zero rows -> all NS see c_net=0.
    ccr_collateral_lf = raw_ccr.ccr_collateral.ccr_collateral
    ccr_collateral_cols = ccr_collateral_lf.collect_schema().names()
    if "netting_set_id" in ccr_collateral_cols and "collateral_value" in ccr_collateral_cols:
        c_net_per_ns = ccr_collateral_lf.group_by("netting_set_id").agg(
            pl.col("collateral_value").fill_null(0.0).sum().alias("c_net")
        )
    else:
        # Empty-collateral path: derive an empty c_net frame keyed by netting set.
        c_net_per_ns = netting_sets_lf.select(
            pl.col("netting_set_id"),
            pl.lit(0.0).alias("c_net"),
        )

    # 5) Compose NS-grain frame for compute_pfe: v_net, c_net, addon_aggregate.
    #    Carries ``addon_by_asset_class`` alongside so the per-class breakdown
    #    rides the same lazy plan into the final select.
    ns_frame = (
        netting_sets_lf.join(ns_trade_aggregates, on="netting_set_id", how="left")
        .join(addon_per_ns, on="netting_set_id", how="left")
        .join(addon_by_class_per_ns, on="netting_set_id", how="left")
        .join(c_net_per_ns, on="netting_set_id", how="left")
        .with_columns(
            [
                pl.col("v_net").fill_null(0.0),
                pl.col("c_net").fill_null(0.0),
                pl.col("addon_aggregate").fill_null(0.0),
            ]
        )
    )

    # Guarantee the Art. 291(5)(c) WWR LGD override column is present so the
    # synthetic-row select below can surface it. ``apply_wwr_gate`` tags the
    # synthetic NS with ``wwr_lgd_override = 1.0`` and the residual NS with
    # null; when the gate did not run (no specific-WWR trades) ``ensure_columns``
    # backfills the schema default (null) so the column rides the lazy plan
    # unchanged. No-op when already present.
    ns_frame = ensure_columns(
        ns_frame, {"wwr_lgd_override": NETTING_SET_SCHEMA["wwr_lgd_override"]}
    )

    # Replacement cost. Unmargined sets follow CRR Art. 275(1):
    #   RC = max(V - C, 0).
    # Margined sets follow CRR Art. 275(2):
    #   RC = max(V - C, TH + MTA - NICA, 0)
    # using the threshold / minimum-transfer-amount / NICA carried on the
    # netting set (NETTING_SET_SCHEMA). Both are surfaced for audit; the
    # unified ``rc`` selects the margined form for margined sets and feeds
    # EAD = alpha * (rc + PFE) inside compute_pfe.
    ns_frame = compute_rc_unmargined(ns_frame)
    ns_frame = compute_rc_margined(ns_frame)
    ns_frame = ns_frame.with_columns(
        pl.coalesce(pl.col("rc_margined"), pl.col("rc_unmargined")).alias("rc")
    )

    # CRR Art. 274(2) second sub-paragraph: join the counterparty_type
    # discriminator (keyed on counterparty_reference, NOT cross-joined — the NS
    # frame is already at counterparty grain via NETTING_SET_SCHEMA) and reduce
    # it to a per-NS ``alpha_applied`` scalar. compute_pfe reads this column
    # when present (else falls back to config_ccr.alpha / 1.4).
    ns_frame = _attach_alpha_applied(ns_frame, counterparties)

    ns_with_ead = compute_pfe(ns_frame, config_ccr)

    # PRA PS1/26 Art. 274(2A): transitional alpha add-on. For legacy
    # CVA-exempt netting sets on the α=1.0 carve-out, phase a fraction of the
    # full alpha add-on (= (α=1.4 − α=1.0) × (RC + PFE) = 0.4 × (RC + PFE))
    # into ``ead_ccr`` across 2027-2029, zero from 2030. Basel 3.1 only — never
    # under CRR (the framework gate resolves the phase factor to 0).
    ns_with_ead = _attach_transitional_add_on(ns_with_ead, reporting_date, is_basel_3_1)

    # 6) Shape into synthetic exposure rows. drawn_amount = ead_ccr so that
    #    the CRM `_initialize_ead` produces ead_pre_crm = ead_ccr (no CCF /
    #    no collateral / no guarantee match) and the SA calculator then
    #    routes it through Classifier's INSTITUTION class at CQS 2 -> 50%.
    return ns_with_ead.select(
        [
            pl.concat_str([pl.lit("ccr__"), pl.col("netting_set_id")]).alias("exposure_reference"),
            # Reconciliation base: a netting set has no legacy per-exposure
            # equivalent, so keep the ``ccr__`` namespace (the base equals the
            # exposure_reference) — a bare netting_set_id could collide with an
            # unrelated loan reference and silently sum EAD on a base-grain key.
            pl.concat_str([pl.lit("ccr__"), pl.col("netting_set_id")]).alias(
                "source_exposure_reference"
            ),
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
            pl.lit("CCR_DERIVATIVE").alias("risk_type"),
            # TODO(CCR-deriv-maturity): emit ccr_effective_maturity for
            # CCR_DERIVATIVE rows (NS-grain .all() daily aggregation over the
            # trade-grain margining inputs) — see Phase 3b.
            # Art. 143 own-estimate LGD carrier for A-IRB routing (P1.215; null =>
            # SA / FIRB downstream), max-per-NS (deterministic + conservative)
            # from the trade aggregation above.
            pl.col("ccr_modelled_lgd"),
            pl.col("netting_set_id").alias("source_netting_set_id"),
            pl.lit("sa_ccr").alias("ccr_method"),
            # CRR Art. 306(1)(c): client-clearing flag for the QCCP 4% trade
            # exposure pin, collapsed to NS grain from the trade-level
            # is_client_cleared (Art. 305(2)). Surfaced as the classifier-aliased
            # ``cp_is_ccp_client_cleared`` so the SA calculator's QCCP branch
            # reads it directly (the CCR counterparty frame carries no
            # is_ccp_client_cleared column to join, so there is no collision).
            pl.col("_ns_is_client_cleared").alias("cp_is_ccp_client_cleared"),
            # Surface the Art. 291(5)(c) WWR LGD override onto the exposure
            # row: 1.0 for a specific-WWR synthetic NS, null otherwise. The
            # downstream IRB consumer (deferred P8.31) reads this to apply
            # LGD = 100%; SA-routed CCR rows carry it as an audit tag only.
            pl.col("wwr_lgd_override"),
            # Preserve the SA-CCR component columns so downstream tests /
            # COREP exports can reconcile the EAD back to RC + PFE without
            # re-running the chain.
            pl.col("addon_aggregate"),
            pl.col("addon_by_asset_class"),
            pl.col("pfe_multiplier"),
            pl.col("pfe_addon"),
            pl.col("rc_unmargined"),
            pl.col("rc_margined"),
            pl.col("rc"),
            # CRR Art. 274(2): the per-NS supervisory alpha actually applied
            # (1.0 carve-out for non-financial / pension-scheme counterparties,
            # 1.4 otherwise). Surfaced as an audit column so downstream tests /
            # COREP exports can reconcile ead_ccr = alpha_applied * (rc + pfe).
            pl.col("alpha_applied"),
            # PRA PS1/26 Art. 274(2A): the phased transitional alpha add-on
            # folded into ead_ccr (0.0 unless the NS is legacy CVA-exempt, on
            # the α=1.0 carve-out, under Basel 3.1, at a 2027-2029 reporting
            # date). Surfaced so downstream tests / COREP exports can reconcile
            # the uplift back out of ead_ccr.
            pl.col("transitional_add_on"),
            pl.col("ead_ccr"),
        ]
    )


def partition_out_sft_rows(
    raw_ccr: RawCCRBundle,
) -> tuple[RawCCRBundle, list[CalculationError]]:
    """Exclude mis-placed SFT trades from the SA-CCR derivative input.

    SFT/FCCM separation (Phase 6): SFT EAD (CRR Art. 271(2), Art. 220-223 FCCM)
    is computed by the peer ``sft_fccm`` stage from ``RawDataBundle.sft``. The
    SA-CCR Art. 274 chain in this module is derivatives-only. Any
    ``transaction_type == "sft"`` trade still present in ``RawDataBundle.ccr`` is
    mis-placed input that the derivative chain would silently mis-price (treating
    a securities-financing transaction as a directional derivative — typically
    yielding ≈£0 EAD for a credit-asset-class SFT with no add-on input, hence
    under-reported exposure).

    Following the project error convention (CLAUDE.md): a data-quality issue is
    reported via the ``list[CalculationError]`` channel, **never** a raised
    exception. This helper returns a derivative-only bundle (the SFT trades, and
    the netting sets / CCR collateral keyed only by those SFT trades, removed) so
    the offending rows cannot reach the Art. 274 chain, plus one
    ``CalculationError(code="CCR020", severity=ERROR, category=DATA_QUALITY)`` per
    offending netting set.

    This single "no SFT rows in ``raw.ccr``" invariant subsumes the
    "both ``raw.ccr`` (with SFT rows) and ``raw.sft`` populated → double-count"
    guard the migration plan listed separately: forbidding SFT trades in
    ``raw.ccr`` removes the only path by which the same SFT EAD could be computed
    twice (once via this chain, once via the ``sft_fccm`` stage), so there is no
    residual double-count path to guard against.

    Args:
        raw_ccr: The CCR input bundle (derivatives expected; SFT rows are the
            mis-placed input this guard strips).

    Returns:
        ``(derivative_only_bundle, errors)``. When the bundle carries no SFT
        trades the input bundle is returned unchanged with an empty error list
        (fast path, no rebuild).

    References:
        CRR Art. 271(2) — SFT EAD via FCCM, not SA-CCR Art. 274.
    """
    trades_lf = raw_ccr.trades.trades
    # ``transaction_type`` is a required TRADE_SCHEMA column (the loader seals it
    # onto every CCR trade frame), so no presence guard is needed.
    is_sft = pl.col("transaction_type") == _SFT_TRANSACTION_TYPE
    # Materialise the SFT side once to enumerate the offending netting sets and
    # build one error per NS. Trade frames are firm-scale; this collect is cheap.
    sft_ns_ids = (
        trades_lf.filter(is_sft)
        .select(pl.col("netting_set_id").unique())
        .collect()["netting_set_id"]
        .to_list()
    )
    if not sft_ns_ids:
        # Fast path: derivatives-only bundle, nothing to strip.
        return raw_ccr, []

    netting_sets_lf = raw_ccr.netting_sets.netting_sets
    ccr_collateral_lf = raw_ccr.ccr_collateral.ccr_collateral

    derivative_only = RawCCRBundle(
        trades=TradeBundle(trades=trades_lf.filter(~is_sft)),
        netting_sets=NettingSetBundle(
            netting_sets=netting_sets_lf.filter(~pl.col("netting_set_id").is_in(sft_ns_ids)),
        ),
        margin_agreements=raw_ccr.margin_agreements,
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=ccr_collateral_lf.filter(~pl.col("netting_set_id").is_in(sft_ns_ids)),
        ),
        failed_trades=raw_ccr.failed_trades,
        default_fund_contributions=raw_ccr.default_fund_contributions,
        errors=list(raw_ccr.errors),
    )

    errors = [
        CalculationError(
            code=CCR_SFT_IN_DERIVATIVE_INPUT_ERROR_CODE,
            message=(
                f"Netting set {ns_id} carries transaction_type='sft' trades in the "
                "SA-CCR derivative input (RawDataBundle.ccr). SFT EAD must be supplied "
                "via RawDataBundle.sft and computed by the FCCM sft_fccm stage "
                "(CRR Art. 271(2), Art. 220-223). The offending rows are excluded "
                "from the Art. 274 derivative chain to avoid mis-pricing."
            ),
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
            regulatory_reference=CCR_SFT_IN_DERIVATIVE_INPUT_REG_REF,
            field_name="transaction_type",
            expected_value="derivative (route SFTs via RawDataBundle.sft)",
            actual_value="sft",
        )
        for ns_id in sft_ns_ids
    ]
    logger.warning(
        "excluded %d netting set(s) carrying transaction_type='sft' from the SA-CCR "
        "derivative chain (route SFTs via RawDataBundle.sft / sft_fccm stage)",
        len(sft_ns_ids),
    )
    return derivative_only, errors


def _attach_mpor_cascade_inputs(
    trades_enriched: pl.LazyFrame,
    netting_sets_lf: pl.LazyFrame,
    margin_agreements_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """Denormalise the Art. 285 MPOR-cascade inputs onto each trade row.

    The margined maturity factor (CRR Art. 279c(2)) consumes a denormalised
    trade frame carrying the Art. 285 cascade drivers. Two left joins (each
    deduplicated to one row per key so they cannot fan out the trade frame)
    bring those drivers onto ``trades_enriched``:

    - keyed on ``netting_set_id`` (NETTING_SET_SCHEMA):
      ``is_margined``, ``number_of_trades``, ``mpor_days`` (→ ``mpor_days_input``),
      ``has_illiquid_collateral_or_hard_to_replace_otc`` (→ ``has_illiquid``)
      and ``margin_agreement_id`` (the join key for the next hop).
    - keyed on ``margin_agreement_id`` (MARGIN_AGREEMENT_SCHEMA):
      ``remargining_frequency_days`` and ``dispute_count_qtr``.

    ``remargining_frequency_days`` is a business-day count (Art. 285(5));
    it is deliberately kept distinct from the calendar-day ``years_to_maturity``
    already on the trade frame.

    Args:
        trades_enriched: Per-trade LazyFrame carrying ``netting_set_id``.
        netting_sets_lf: Netting-set LazyFrame (NETTING_SET_SCHEMA).
        margin_agreements_lf: Margin-agreement LazyFrame (MARGIN_AGREEMENT_SCHEMA).

    Returns:
        ``trades_enriched`` with the Art. 285 cascade columns attached.

    References:
        CRR Art. 285(2)-(5); CRR Art. 279c(2).
    """
    ns_cascade = netting_sets_lf.select(
        pl.col("netting_set_id"),
        pl.col("is_margined"),
        pl.col("number_of_trades"),
        pl.col("mpor_days").alias("mpor_days_input"),
        pl.col("has_illiquid_collateral_or_hard_to_replace_otc").alias("has_illiquid"),
        pl.col("margin_agreement_id"),
    ).unique(subset=["netting_set_id"])

    ma_terms = margin_agreements_lf.select(
        pl.col("margin_agreement_id"),
        pl.col("remargining_frequency_days"),
        pl.col("dispute_count_qtr"),
    ).unique(subset=["margin_agreement_id"])

    return trades_enriched.join(ns_cascade, on="netting_set_id", how="left").join(
        ma_terms, on="margin_agreement_id", how="left"
    )


def _attach_alpha_applied(
    ns_frame: pl.LazyFrame,
    counterparties: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """Attach the per-NS supervisory-alpha column ``alpha_applied``.

    CRR Art. 274(2) second sub-paragraph: the default supervisory alpha is 1.4
    (``SA_CCR_ALPHA``); netting sets whose counterparty is a non-financial
    counterparty (EMIR Art. 2(9)), a pension-scheme arrangement (EMIR Art. 2(10))
    or a pension-scheme default-fund-contribution position receive the
    ``SA_CCR_ALPHA_CARVE_OUT`` (1.0). The discriminator is the COUNTERPARTY_SCHEMA
    ``counterparty_type`` column, joined onto ``ns_frame`` keyed on
    ``counterparty_reference`` (one NS row in, one NS row out — no fan-out).

    Backward-compatible defaults: when ``counterparties`` is None, lacks a
    ``counterparty_type`` column (Python-bundle path that skips ``enforce_schema``),
    or a row's ``counterparty_type`` is null, the netting set keeps alpha = 1.4.

    Args:
        ns_frame: Netting-set-grain LazyFrame carrying ``counterparty_reference``.
        counterparties: Optional counterparty LazyFrame (COUNTERPARTY_SCHEMA).

    Returns:
        ``ns_frame`` with a new ``alpha_applied: Float64`` column.

    References:
        CRR Art. 274(2) second sub-paragraph; EMIR Art. 2(9) / 2(10);
        BCBS CRE52.1.
    """
    carve_out = _SA_CCR_ALPHA_CARVE_OUT
    standard = _SA_CCR_ALPHA

    has_type = (
        counterparties is not None
        and "counterparty_type" in counterparties.collect_schema().names()
    )
    if not has_type or counterparties is None:
        # No discriminator available — every NS keeps the standard alpha = 1.4.
        return ns_frame.with_columns(pl.lit(standard).alias("alpha_applied"))

    cp_type = counterparties.select(
        pl.col("counterparty_reference"),
        pl.col("counterparty_type"),
    ).unique(subset=["counterparty_reference"])

    # Keyed left join (NOT a cross-join): preserves one row per netting set.
    return ns_frame.join(cp_type, on="counterparty_reference", how="left").with_columns(
        pl.when(pl.col("counterparty_type").is_in(CCR_ALPHA_CARVE_OUT_COUNTERPARTY_TYPES))
        .then(pl.lit(carve_out))
        .otherwise(pl.lit(standard))
        .alias("alpha_applied")
    )


def _attach_transitional_add_on(
    ns_with_ead: pl.LazyFrame,
    reporting_date: date,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """Attach the PRA PS1/26 Art. 274(2A) transitional alpha add-on.

    Computes a ``transitional_add_on`` column and folds it into ``ead_ccr``.
    The add-on is the phased fraction of the full alpha add-on, where the full
    add-on equals the difference between EAD at α=1.4 and EAD at α=1.0::

        add_on = phase × (SA_CCR_ALPHA − SA_CCR_ALPHA_CARVE_OUT) × (rc + pfe_addon)
               = phase × 0.4 × (rc + pfe_addon)

    Folding ``add_on`` into the base ``ead_ccr`` (which for an in-scope NFC is
    ``1.0 × (rc + pfe_addon)``) yields ``(rc + pfe_addon) × (1 + 0.4 × phase)``.

    Gate (all must hold, else ``transitional_add_on = 0.0``):
        1. ``is_basel_3_1`` — Basel 3.1 only (CRR has no Art. 274(2A)).
        2. ``phase_factor > 0`` — reporting year in {2027, 2028, 2029}.
        3. ``_ns_is_legacy_cva_exempt == True`` — legacy CVA-exempt netting set.
        4. ``alpha_applied == SA_CCR_ALPHA_CARVE_OUT`` (1.0) — coherence: an
           α=1.4 financial counterparty receives nothing.

    Conditions (1) and (2) are scalar / Python-resolved at build time, so under
    CRR or at a 2030+ reporting date the phase factor is 0 and the add-on is a
    constant 0.0 for every netting set — preserving pre-P8.29 ``ead_ccr``.

    Art. 274(2B) (leverage-ratio exclusion) is moot: this engine exposes no
    leverage-ratio EAD path, so there is no bifurcation to build.

    Args:
        ns_with_ead: Netting-set-grain LazyFrame carrying ``rc``, ``pfe_addon``,
            ``alpha_applied``, ``ead_ccr`` and ``_ns_is_legacy_cva_exempt``.
        reporting_date: As-of date; ``reporting_date.year`` selects the phase.
        is_basel_3_1: Framework flag; the add-on is Basel 3.1 only.

    Returns:
        ``ns_with_ead`` with a new ``transitional_add_on: Float64`` column and
        an ``ead_ccr`` updated to include the (possibly zero) add-on.

    References:
        PRA PS1/26 Art. 274(2A)-(2B); CRR Art. 274(2).
    """
    # Phase factor is resolved at build time: 0 under CRR or for years not in
    # the Art. 274(2A) schedule (e.g. 2030+).
    phase_factor = _TRANSITIONAL_ADDON_PHASE.get(reporting_date.year, 0.0) if is_basel_3_1 else 0.0
    alpha_uplift = _SA_CCR_ALPHA - _SA_CCR_ALPHA_CARVE_OUT
    carve_out = _SA_CCR_ALPHA_CARVE_OUT

    if phase_factor <= 0.0:
        # Framework / year gate closed — add-on is a constant 0.0 and ead_ccr
        # is unchanged. No row qualifies, so no fold is applied.
        return ns_with_ead.with_columns(pl.lit(0.0).alias("transitional_add_on"))

    in_scope = pl.col("_ns_is_legacy_cva_exempt").fill_null(False) & (
        pl.col("alpha_applied") == carve_out
    )
    add_on_expr = (
        pl.when(in_scope)
        .then(phase_factor * alpha_uplift * (pl.col("rc") + pl.col("pfe_addon")))
        .otherwise(0.0)
        .alias("transitional_add_on")
    )
    return ns_with_ead.with_columns(add_on_expr).with_columns(
        (pl.col("ead_ccr") + pl.col("transitional_add_on")).alias("ead_ccr")
    )
