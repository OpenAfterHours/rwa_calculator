"""
Collateral allocation and LGD calculation for CRM processing.

Pipeline position:
    EAD initialisation -> apply_collateral -> Guarantees

Key responsibilities:
- Netting collateral generation (CRR Art. 195)
- Haircut application and maturity mismatch
- Multi-level collateral allocation (direct / facility / counterparty)
- SA EAD reduction via eligible financial collateral
- F-IRB LGD calculation with supervisory values
- A-IRB LGD Modelling Collateral Method (Art. 169A/169B)
- Overcollateralisation and minimum threshold checks

References:
    CRR Art. 223-224, 230: Collateral haircuts and allocation
    CRR Art. 161: F-IRB supervisory LGD
    PRA PS1/26 Art. 169A/169B: LGD Modelling Collateral Method
    CRE22.52-53, CRE32.9-12: Basel 3.1 equivalents
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_INELIGIBLE_IRB_COLLATERAL, crm_warning
from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES, NON_ELIGIBLE_RE_TYPES
from rwa_calc.domain.enums import AIRBCollateralMethod, ApproachType
from rwa_calc.engine.crm.expressions import (
    CRM_ALLOC_COLUMNS,
    WATERFALL_ORDER,
    beneficiary_level_expr,
    collateral_category_expr,
    collateral_lgd_expr,
    is_financial_collateral_type_expr,
    overcollateralisation_ratio_expr,
    subordinated_unsecured_lgd,
    supervisory_lgd_values,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.observability.audit_cache import sink_audit
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import lookup_float_map
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack


def airb_lgd_preserved_expr(
    config: CalculationConfig,
    schema_names: set[str],
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.Expr:
    """
    Build a boolean expression marking exposures whose modelled LGD is preserved.

    True iff the row is AIRB and CRM does not overwrite ``lgd_pre_crm`` with the
    supervisory formula. Used both to drive the LGD branch in
    ``_apply_collateral_unified`` and to define the AIRB-eligible pro-rata pool
    for collateral allocation: rows where the modelled LGD is preserved are
    members of the AIRB pool, all others fall in the non-AIRB pool.

    Returns False for FIRB / SA / Slotting and for AIRB rows that fall back to
    the supervisory formula under Art. 169B (insufficient data) or under the
    Foundation Collateral Method election.

    References:
        CRR Art. 181 — AIRB own-LGD framework
        CRE36.34-36 — collateral effects reflected in own LGD estimates
        Basel 3.1 Art. 169A/169B — LGD Modelling Collateral Method
        Basel 3.1 Art. 191A — AIRB collateral method election
    """
    is_airb = pl.col("approach") == ApproachType.AIRB.value
    airb_method = config.airb_collateral_method
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    airb_collateral_method_applies = resolved_pack.feature("airb_lgd_collateral_method_applicable")

    if airb_collateral_method_applies and airb_method == AIRBCollateralMethod.FOUNDATION:
        return pl.lit(False)
    if airb_collateral_method_applies and airb_method == AIRBCollateralMethod.LGD_MODELLING:
        if "has_sufficient_collateral_data" in schema_names:
            return is_airb & pl.col("has_sufficient_collateral_data").fill_null(True)
        return is_airb
    return is_airb


def find_misdirected_airb_model_collateral(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> list[tuple[str, str]]:
    """
    Identify direct collateral rows flagged as ``is_airb_model_collateral`` but
    pledged to an exposure outside the AIRB-eligible pool.

    The flag asserts that the collateral has been used to construct the firm's
    internal LGD model. Direct allocation onto a non-AIRB-pool exposure
    therefore has no LGD effect (the supervisory formula doesn't reach it via
    this row) and indicates a data-quality issue — typically a mis-tagged row
    or a pledge that should be at facility/counterparty level.

    Returns:
        A list of ``(collateral_reference, exposure_reference)`` tuples for
        each misdirected row. Caller emits CRM006 warnings.
    """
    coll_schema = collateral.collect_schema()
    if "is_airb_model_collateral" not in coll_schema.names():
        return []
    if "beneficiary_type" not in coll_schema.names():
        return []
    if "collateral_reference" not in coll_schema.names():
        return []

    schema_names = set(exposures.collect_schema().names())
    pool_lookup = exposures.select(
        pl.col("exposure_reference"),
        airb_lgd_preserved_expr(config, schema_names, pack=pack).alias("_is_airb_pool"),
    )

    bt_lower = pl.col("beneficiary_type").str.to_lowercase()
    misdirected = (
        collateral.filter(
            pl.col("is_airb_model_collateral").fill_null(False)
            & bt_lower.is_in(DIRECT_BENEFICIARY_TYPES)
        )
        .join(
            pool_lookup,
            left_on="beneficiary_reference",
            right_on="exposure_reference",
            how="left",
        )
        .filter(~pl.col("_is_airb_pool").fill_null(False))
        .select("collateral_reference", "beneficiary_reference")
        .collect()
    )
    return [
        (row["collateral_reference"], row["beneficiary_reference"])
        for row in misdirected.iter_rows(named=True)
    ]


@cites("CRR Art. 195")
@cites("CRR Art. 219")
@cites("CRR Art. 223")
def generate_netting_collateral(
    exposures: pl.LazyFrame,
) -> pl.LazyFrame | None:
    """
    Generate synthetic cash collateral from negative-drawn netting-eligible loans.

    When a loan has a negative drawn amount (credit balance / deposit) and carries
    a ``netting_agreement_reference`` (CRR Art. 195/219), the absolute value of
    that negative balance can reduce other exposures covered by the SAME netting
    agreement — treated as synthetic cash collateral.

    Netting is driven SOLELY by ``netting_agreement_reference``: only exposures
    sharing the same reference net together. This reflects the legal right of
    set-off, which is defined by the netting agreement itself — not by facility
    hierarchy or counterparty. A deposit from one counterparty may net a loan to a
    different counterparty (and across different facilities) iff both carry the
    same reference; conversely two exposures in the same facility do NOT net unless
    they share the reference.

    CRR Art. 219 limits on-balance-sheet netting to drawn loans and deposits
    (cash-on-cash). Synthetic cash collateral is allocated pro-rata by the drawn
    portion (`on_bs_for_ead`) to positive-drawn LOAN siblings carrying the same
    reference — contingents and synthetic facility_undrawn rows are
    off-balance-sheet and excluded from the beneficiary set. Netting pools are
    grouped by (netting_agreement_reference, currency) so the haircut pipeline can
    apply FX haircuts when the pool currency differs from the sibling's currency.

    Args:
        exposures: Exposures with ead_for_crm, on_bs_for_ead, exposure_type set

    Returns:
        LazyFrame of synthetic collateral rows, or None if no netting applies
    """
    schema = exposures.collect_schema()
    schema_names = set(schema.names())
    if "netting_agreement_reference" not in schema_names:
        return None

    # Graceful fallback for direct unit-test callers (production always
    # supplies ead_for_crm via _initialize_ead, on_bs_for_ead via _compute_ead,
    # and exposure_type via hierarchy).
    if "ead_for_crm" not in schema_names:
        exposures = exposures.with_columns(pl.col("ead_gross").alias("ead_for_crm"))
    if "on_bs_for_ead" not in schema_names:
        interest_expr = (
            pl.col("interest").fill_null(0.0).clip(lower_bound=0.0)
            if "interest" in schema_names
            else pl.lit(0.0)
        )
        exposures = exposures.with_columns(
            (pl.col("drawn_amount").clip(lower_bound=0.0) + interest_expr).alias("on_bs_for_ead")
        )
    if "exposure_type" not in schema_names:
        exposures = exposures.with_columns(pl.lit("loan").alias("exposure_type"))

    # Negative-drawn loans carrying a netting agreement reference provide the pool
    negative_loans = exposures.filter(
        pl.col("netting_agreement_reference").is_not_null() & (pl.col("drawn_amount") < 0)
    )

    # Sum abs(drawn_amount) per (netting_agreement_reference, currency) → netting pool.
    # Currency is kept so the synthetic collateral carries the source currency,
    # allowing the haircut pipeline to apply FX haircuts when currencies differ.
    netting_pool = (
        negative_loans.group_by(["netting_agreement_reference", "currency"])
        .agg(
            pl.col("drawn_amount").abs().sum().alias("netting_pool"),
        )
        .rename({"currency": "_pool_currency"})
    )

    # CRR Art. 219: drawn-on-drawn cash netting. Synthetic cash collateral may
    # only benefit the drawn portion of loan exposures — contingents and
    # facility_undrawn synthetic rows are off-balance-sheet and ineligible. A
    # sibling matches a pool iff it carries the same netting_agreement_reference.
    positive_siblings = exposures.filter(
        (pl.col("exposure_type") == "loan")
        & (pl.col("on_bs_for_ead") > 0)
        & pl.col("netting_agreement_reference").is_not_null()
    ).select(
        "exposure_reference",
        "netting_agreement_reference",
        "currency",
        "on_bs_for_ead",
        "maturity_date",
    )

    # Match siblings to pools by shared netting agreement reference.
    matched = positive_siblings.join(
        netting_pool,
        on="netting_agreement_reference",
        how="inner",
    )

    # Total drawn EAD per pool for pro-rata allocation. CRR Art. 219 nets cash
    # against drawn loans, so the pro-rata basis is the on-BS (drawn) portion,
    # NOT ead_for_crm (which includes the off-BS nominal at CCF=100% per
    # Art. 223(4) — that override is for collateral valuation, not for OBS
    # netting allocation basis).
    facility_totals = matched.group_by("netting_agreement_reference", "_pool_currency").agg(
        pl.col("on_bs_for_ead").sum().alias("_facility_total_drawn"),
    )

    # Join totals back for pro-rata
    allocated = matched.join(
        facility_totals,
        on=["netting_agreement_reference", "_pool_currency"],
        how="left",
    ).filter(pl.col("_facility_total_drawn") > 0)

    # Pro-rata market_value per sibling by drawn portion (Art. 219).
    allocated = allocated.with_columns(
        (pl.col("netting_pool") * pl.col("on_bs_for_ead") / pl.col("_facility_total_drawn")).alias(
            "market_value"
        ),
    )

    # Build synthetic collateral rows — currency from the pool (source of funds)
    synthetic = allocated.select(
        (pl.lit("NETTING_") + pl.col("exposure_reference")).alias("collateral_reference"),
        pl.lit("cash").alias("collateral_type"),
        pl.col("_pool_currency").alias("currency"),
        pl.col("maturity_date"),
        pl.col("market_value"),
        pl.lit(None).cast(pl.Float64).alias("nominal_value"),
        pl.lit(None).cast(pl.Float64).alias("pledge_percentage"),
        pl.lit("loan").alias("beneficiary_type"),
        pl.col("exposure_reference").alias("beneficiary_reference"),
        pl.lit(None).cast(pl.Int8).alias("issuer_cqs"),
        pl.lit(None).cast(pl.String).alias("issuer_type"),
        pl.lit(None).cast(pl.Float64).alias("residual_maturity_years"),
        pl.lit(True).alias("is_eligible_financial_collateral"),
        pl.lit(True).alias("is_eligible_irb_collateral"),
        pl.lit(None).cast(pl.Date).alias("valuation_date"),
        pl.lit(None).cast(pl.String).alias("valuation_type"),
        pl.lit(None).cast(pl.String).alias("property_type"),
        pl.lit(None).cast(pl.Float64).alias("property_ltv"),
        pl.lit(None).cast(pl.Boolean).alias("is_income_producing"),
        pl.lit(None).cast(pl.Boolean).alias("is_adc"),
        pl.lit(None).cast(pl.Boolean).alias("is_presold"),
    )

    return synthetic


@cites("PS1/26 Art. 230(2)")
@cites("PS1/26 Art. 230(1)")
@cites("CRR Art. 223")
@cites("CRR Art. 230")
def apply_collateral(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
    config: CalculationConfig,
    haircut_calculator: HaircutCalculator,
    build_exposure_lookups_fn: Callable,
    join_collateral_to_lookups_fn: Callable,
    resolve_pledge_from_joined_fn: Callable,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Apply collateral to reduce EAD (SA) or LGD (IRB).

    Pre-computes shared exposure lookups once, then joins ALL lookup columns
    (EAD, currency, maturity) in a single pass of 3 joins. Pledge resolution
    and currency/maturity derivation operate on pre-joined columns — no
    additional joins needed.

    Args:
        exposures: Exposures with ead_gross
        collateral: Collateral data
        config: Calculation configuration
        haircut_calculator: HaircutCalculator instance
        build_exposure_lookups_fn: Function to build exposure lookups
        join_collateral_to_lookups_fn: Function to join collateral to lookups
        resolve_pledge_from_joined_fn: Function to resolve pledge percentages

    Returns:
        Exposures with collateral effects applied
    """
    # Tag each exposure with its AIRB-pool membership so downstream pro-rata
    # bases can be split into AIRB and non-AIRB pools. CRR Art. 181 / Basel 3.1
    # Art. 169A: AIRB own LGD already reflects collateral, so collateral
    # incorporated in the model must not also be allocated to non-AIRB
    # exposures of the same counterparty.
    schema_names = set(exposures.collect_schema().names())

    # Graceful fallback for direct unit-test callers that hand-build the
    # exposures frame without going through _initialize_ead.  In production
    # both columns are always present.  For pure on-BS rows the defaults
    # produce identical behaviour to the explicit columns, so existing
    # tests stay green without modification.
    fallback_cols: list[pl.Expr] = []
    if "ead_for_crm" not in schema_names:
        fallback_cols.append(pl.col("ead_gross").alias("ead_for_crm"))
    if "effective_ccf" not in schema_names:
        fallback_cols.append(pl.lit(1.0).alias("effective_ccf"))
    if fallback_cols:
        exposures = exposures.with_columns(fallback_cols)
        schema_names |= {expr.meta.output_name() for expr in fallback_cols}

    # S9h: resolve the pack once; the collateral-LGD regime branches downstream
    # (haircut maturity bands, AIRB pool membership, FSE split, Art. 230(2) sub-rows)
    # read honest cited Features off it instead of a single config.is_basel_3_1 bool.
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # CRR Art. 223(5) FCCM exposure volatility haircut (HE). Computed once on
    # the exposure frame so the SA branch in ``_apply_collateral_unified`` can
    # gross E by (1 + HE). Non-SFT / cash / standard-loan rows yield HE = 0.
    exposures = haircut_calculator.apply_exposure_haircut(
        exposures,
        resolved_pack.feature("collateral_haircut_maturity_bands_revised"),
        pack=resolved_pack,
    )

    exposures = exposures.with_columns(
        airb_lgd_preserved_expr(config, schema_names, pack=resolved_pack).alias("_is_airb_pool")
    )

    # Pre-compute shared exposure lookups once
    direct_lookup, facility_lookup, cp_lookup = build_exposure_lookups_fn(exposures)

    # Materialise the small lookup frames in parallel to prevent plan-tree
    # duplication. Each lookup is referenced in multiple downstream joins;
    # without this, Polars re-evaluates the group_by/select at each reference.
    # collect_all runs all 3 concurrently and enables CSE on shared upstream.
    direct_df, facility_df, cp_df = pl.collect_all([direct_lookup, facility_lookup, cp_lookup])
    direct_lookup = direct_df.lazy()
    facility_lookup = facility_df.lazy()
    cp_lookup = cp_df.lazy()

    # Derive pool-aware counterparty EAD totals from the lookups. Unflagged
    # collateral pro-rates over the non-AIRB pool only; flagged collateral
    # (is_airb_model_collateral=True) pro-rates over the AIRB pool only.
    # Facility-level subtree totals are derived per-ancestor inside
    # ``_apply_collateral_unified`` (``_cascade_facility_collateral``) so that
    # collateral pledged at any ancestor facility cascades over its whole
    # descendant subtree for nested facility hierarchies.
    cp_ead_totals = cp_lookup.select(
        pl.col("_ben_ref_cp").alias("counterparty_reference"),
        pl.col("_ead_cp").alias("_cp_ead_total"),
        pl.col("_ead_cp_airb").alias("_cp_ead_total_airb"),
        pl.col("_ead_cp_non_airb").alias("_cp_ead_total_non_airb"),
    )

    # Single pass: join all lookup columns (EAD, currency, maturity)
    collateral = join_collateral_to_lookups_fn(
        collateral, direct_lookup, facility_lookup, cp_lookup
    )

    # Resolve pledge_percentage → market_value (uses pre-joined _beneficiary_ead)
    collateral = resolve_pledge_from_joined_fn(collateral)

    # Apply haircuts to collateral (no longer needs exposures)
    adjusted_collateral = haircut_calculator.apply_haircuts(collateral, config, pack=pack)

    # Apply maturity mismatch using actual exposure maturity (Art. 238)
    adjusted_collateral = haircut_calculator.apply_maturity_mismatch(adjusted_collateral, config)

    # Opt-in audit cache: persist the per-collateral haircut frame for inspection.
    # No-op unless config.audit_cache_dir is set. Surfaces fx_haircut /
    # collateral_haircut / value_after_haircut / value_after_maturity_adj — the
    # diagnostic columns users need to confirm whether H_fx is firing on a row.
    sink_audit(adjusted_collateral, config, "collateral_haircuts")

    return _apply_collateral_unified(
        exposures,
        adjusted_collateral,
        config,
        cp_ead_totals,
        pack=resolved_pack,
        errors=errors,
    )


def _resolve_pack_for_lgd(
    pack: ResolvedRulepack | None,
    config: CalculationConfig | None,
    is_basel_3_1: bool,
) -> ResolvedRulepack:
    """Resolve a rulepack for the (date-independent) supervisory-LGD lookup.

    Production always supplies ``pack`` (threaded) or ``config``; the
    ``is_basel_3_1`` fallback (with a placeholder reporting date — the LGD
    tables carry no Schedule, so the date is immaterial to the lookup) keeps the
    direct unit-test callers of ``apply_firb_supervisory_lgd_no_collateral``
    working without a config.
    """
    if pack is not None:
        return pack
    if config is not None:
        return RulepackV0.from_config(config).pack
    return resolve("b31" if is_basel_3_1 else "crr", date(2026, 1, 1))


@cites("CRR Art. 161")
def apply_firb_supervisory_lgd_no_collateral(
    exposures: pl.LazyFrame,
    config: CalculationConfig | None = None,
    *,
    pack: ResolvedRulepack | None = None,
    is_basel_3_1: bool = False,
) -> pl.LazyFrame:
    """
    Apply F-IRB supervisory LGD when no collateral is available.

    For F-IRB exposures without collateral, uses supervisory LGD values:
    - CRR Art. 161(1)(a): Senior unsecured 45%, Subordinated 75%
    - Basel 3.1 Art. 161(1)(a)/(aa): FSE senior 45%, non-FSE senior 40%, Sub 75%

    For A-IRB exposures under Basel 3.1:
    - LGD Modelling + insufficient data (Art. 169B): own lgd_unsecured as LGDU
    - Foundation election: supervisory LGDU (same as F-IRB)
    - LGD Modelling + sufficient data: keep modelled LGD unchanged

    Under CRR, A-IRB exposures always keep their modelled LGD.

    Args:
        exposures: Exposures with lgd_pre_crm
        config: CalculationConfig (optional, for AIRB collateral method)
        pack: Resolved rulepack; production threads the run's pack.
        is_basel_3_1: No-config bootstrap regime hint for _resolve_pack_for_lgd
            (direct unit-test path only). The regime BRANCHES read cited Features
            off the resolved pack, not this flag (S9h).

    Returns:
        Exposures with lgd_post_crm set for F-IRB (and qualifying A-IRB)
    """
    resolved_pack = _resolve_pack_for_lgd(pack, config, is_basel_3_1)
    # S9h: read the regime branches as honest cited Features off the same resolved
    # pack that supplies the LGD values. firb_fse_senior_lgd_split gates the FSE
    # 45/40 split; airb_lgd_collateral_method_applicable gates the B31 Art. 169A/169B
    # AIRB collateral-method branches (CRR AIRB is free-form).
    fse_senior_lgd_split = resolved_pack.feature("firb_fse_senior_lgd_split")
    airb_collateral_method_applies = resolved_pack.feature("airb_lgd_collateral_method_applicable")
    lgd_values = supervisory_lgd_values(resolved_pack)
    lgd_senior = lgd_values["unsecured"]
    lgd_subordinated = subordinated_unsecured_lgd(resolved_pack)

    # Add collateral-related columns with zero values for consistency
    exposures = exposures.with_columns(
        [
            pl.lit(0.0).alias("total_collateral_for_lgd"),
            pl.lit(0.0).alias("collateral_coverage_pct"),
        ]
    )

    # Determine LGD based on seniority for F-IRB
    schema_names = set(exposures.collect_schema().names())
    is_subordinated = (
        pl.col("seniority").fill_null("").str.to_lowercase().is_in(["subordinated", "junior"])
        if "seniority" in schema_names
        else pl.lit(False)
    )

    # Under Basel 3.1, FSE senior unsecured = 45% (Art. 161(1)(a));
    # non-FSE senior unsecured = 40% (Art. 161(1)(aa)).
    # Under CRR, all senior unsecured = 45% (no FSE distinction).
    if fse_senior_lgd_split and "cp_is_financial_sector_entity" in schema_names:
        lgd_senior_fse = lgd_values["unsecured_fse"]
        lgd_senior_expr = (
            pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
            .then(pl.lit(lgd_senior_fse))
            .otherwise(pl.lit(lgd_senior))
        )
    else:
        lgd_senior_expr = pl.lit(lgd_senior)

    # --- Determine AIRB treatment (Art. 169A/169B) ---
    airb_method = config.airb_collateral_method if config else None
    is_airb = pl.col("approach") == ApproachType.AIRB.value

    if airb_collateral_method_applies and airb_method == AIRBCollateralMethod.FOUNDATION:
        # AIRB Foundation election: use supervisory LGDU (same as FIRB)
        uses_formula = (pl.col("approach") == ApproachType.FIRB.value) | is_airb
    elif (
        airb_collateral_method_applies
        and airb_method == AIRBCollateralMethod.LGD_MODELLING
        and "has_sufficient_collateral_data" in schema_names
    ):
        # Art. 169B: AIRB with insufficient data → use own lgd_unsecured
        _is_169b = is_airb & (
            pl.col("has_sufficient_collateral_data").fill_null(True) == False  # noqa: E712
        )
        own_lgdu = (
            pl.coalesce(pl.col("lgd_unsecured"), pl.col("lgd_pre_crm"))
            if "lgd_unsecured" in schema_names
            else pl.col("lgd_pre_crm")
        )
        # Build the expression: FIRB uses supervisory, AIRB 169B uses own, AIRB full keeps modelled
        exposures = exposures.with_columns(
            [
                pl.when((pl.col("approach") == ApproachType.FIRB.value) & is_subordinated)
                .then(pl.lit(lgd_subordinated))
                .when(pl.col("approach") == ApproachType.FIRB.value)
                .then(lgd_senior_expr)
                .when(_is_169b & is_subordinated)
                .then(pl.lit(lgd_subordinated))
                .when(_is_169b)
                .then(own_lgdu)
                .otherwise(pl.col("lgd_pre_crm"))
                .alias("lgd_post_crm"),
            ]
        )
        return exposures
    else:
        # CRR or no method: standard FIRB/AIRB split
        uses_formula = pl.col("approach") == ApproachType.FIRB.value

    exposures = exposures.with_columns(
        [
            pl.when(uses_formula & is_subordinated)
            .then(pl.lit(lgd_subordinated))  # Subordinated (same both frameworks)
            .when(uses_formula)
            .then(lgd_senior_expr)  # Senior unsecured (FSE-aware under B31)
            .otherwise(pl.col("lgd_pre_crm"))  # A-IRB or SA: keep existing
            .alias("lgd_post_crm"),
        ]
    )

    return exposures


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _record_ineligible_irb_collateral(
    annotated: pl.LazyFrame,
    not_attested: pl.Expr,
    receivables_too_long: pl.Expr,
    errors: list[CalculationError],
) -> None:
    """Append one CRM014 warning per FIRB FCM non-financial collateral row zeroed
    by the Art. 199(2)/(5)/(6) eligibility gate.

    Targeted collect of the gated rows only — the accepted data-quality emission
    idiom (P1.264); the collateral table is a small dimension frame, so
    materialising just the gated rows' references is cheap.
    """
    names = annotated.collect_schema().names()
    select_cols: list[pl.Expr] = [
        not_attested.alias("_not_attested"),
        receivables_too_long.alias("_recv_long"),
    ]
    select_cols.extend(
        pl.col(c) for c in ("collateral_reference", "beneficiary_reference") if c in names
    )
    gated = annotated.filter(not_attested | receivables_too_long).select(select_cols).collect()
    for row in gated.iter_rows(named=True):
        coll_ref = row.get("collateral_reference")
        ben_ref = row.get("beneficiary_reference")
        reason = (
            "its original maturity exceeds 1 year (Art. 199(5))"
            if row.get("_recv_long")
            else "it is not attested as eligible IRB collateral "
            "(is_eligible_irb_collateral is False/unset; Art. 199(2)/(5)/(6))"
        )
        errors.append(
            crm_warning(
                ERROR_INELIGIBLE_IRB_COLLATERAL,
                f"Non-financial collateral '{coll_ref}' securing exposure "
                f"'{ben_ref}' is ineligible under the FIRB Foundation Collateral "
                f"Method because {reason}; it is zeroed and the secured LGD reverts "
                f"to the unsecured supervisory value.",
                exposure_reference=ben_ref,
                regulatory_reference="CRR Art. 199(2)/(5)/(6)",
            )
        )


@cites("CRR Art. 199")
@cites("PS1/26 Art. 199")
def _apply_collateral_unified(
    exposures: pl.LazyFrame,
    adjusted_collateral: pl.LazyFrame,
    config: CalculationConfig,
    cp_ead_totals: pl.LazyFrame,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Unified EAD + LGD collateral allocation in a single pass.

    Performs a single group_by over all collateral levels (direct, facility,
    counterparty) and joins back to exposures for both SA EAD reduction and
    F-IRB LGD calculation.

    Art. 231 sequential fill: when multiple collateral types secure an
    exposure, each type absorbs exposure starting from the lowest LGDS.
    The institution receives the most favourable ordering (lowest LGDS first):
    financial (0%) -> covered_bond (11.25%) -> receivables -> real_estate
    -> other_physical.  This replaces the former pro-rata allocation.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    # S9h: regime branches read honest cited Features off the resolved pack.
    # firb_fse_senior_lgd_split → FSE 45/40 split; firb_overcollateralisation_divisor_
    # applies → CRR Art. 230(2) subordinated secured-portion LGDS rows (B31 LGD* drops
    # them); airb_lgd_collateral_method_applicable → B31 Art. 169A/169B AIRB method.
    fse_senior_lgd_split = resolved_pack.feature("firb_fse_senior_lgd_split")
    overcollateralisation_step_function = resolved_pack.feature(
        "firb_overcollateralisation_divisor_applies"
    )
    airb_collateral_method_applies = resolved_pack.feature("airb_lgd_collateral_method_applicable")
    lgd_values = supervisory_lgd_values(resolved_pack)
    lgd_subordinated = subordinated_unsecured_lgd(resolved_pack)
    lgd_unsecured = lgd_values["unsecured"]

    # LGDS values per waterfall category (Art. 230/231)
    lgds = {key: lgd_values[key] for _, key, _ in WATERFALL_ORDER}

    # Under Basel 3.1, FSE senior unsecured LGDU = 45% (Art. 161(1)(a));
    # non-FSE = 40% (Art. 161(1)(aa)). Under CRR, all = 45%.
    exposure_schema = exposures.collect_schema()
    _has_fse_col = (
        fse_senior_lgd_split and "cp_is_financial_sector_entity" in exposure_schema.names()
    )
    if _has_fse_col:
        lgd_unsecured_fse = lgd_values["unsecured_fse"]

    # Defensive: fill in pool-aware columns when callers (typically unit tests)
    # construct ead-total frames or exposures without them. Missing pool flag
    # → all exposures treated as non-AIRB pool, which matches legacy behaviour
    # (unflagged collateral pro-rates over the full population).
    if "_is_airb_pool" not in exposure_schema.names():
        exposures = exposures.with_columns(pl.lit(False).alias("_is_airb_pool"))

    # CRR Art. 223(4) override: ead_for_crm is the CCF=100% basis. Production
    # always supplies it via _initialize_ead; direct unit-test callers may
    # not, in which case we fall back to ead_gross (correct for pure on-BS
    # rows where the two are equal by construction).
    if "ead_for_crm" not in exposure_schema.names():
        exposures = exposures.with_columns(pl.col("ead_gross").alias("ead_for_crm"))
    if "effective_ccf" not in exposure_schema.names():
        exposures = exposures.with_columns(pl.lit(1.0).alias("effective_ccf"))

    # Facility-ancestor closure for the multi-level facility collateral cascade.
    # Production supplies ``ancestor_facilities`` (parent + all ancestors up to
    # root, incl. self) from the HierarchyResolver. Direct unit-test callers and
    # single-level inputs fall back to the 1-element [parent] list, which makes
    # the cascade in ``_cascade_facility_collateral`` reduce exactly to the
    # legacy single-level allocation.
    if "ancestor_facilities" not in exposure_schema.names():
        if "parent_facility_reference" in exposure_schema.names():
            exposures = exposures.with_columns(
                pl.concat_list("parent_facility_reference").alias("ancestor_facilities")
            )
        else:
            exposures = exposures.with_columns(
                pl.lit(None, dtype=pl.List(pl.String)).alias("ancestor_facilities")
            )

    cp_totals_schema = cp_ead_totals.collect_schema().names()
    cp_total_fills: list[pl.Expr] = []
    if "_cp_ead_total_non_airb" not in cp_totals_schema:
        cp_total_fills.append(pl.col("_cp_ead_total").alias("_cp_ead_total_non_airb"))
    if "_cp_ead_total_airb" not in cp_totals_schema:
        cp_total_fills.append(pl.lit(0.0).alias("_cp_ead_total_airb"))
    if cp_total_fills:
        cp_ead_totals = cp_ead_totals.with_columns(cp_total_fills)

    collateral_schema = adjusted_collateral.collect_schema()

    # --- Determine eligible expression for EAD reduction ---
    if "is_eligible_financial_collateral" in collateral_schema:
        is_eligible = pl.col("is_eligible_financial_collateral")
    else:
        is_eligible = ~pl.col("collateral_type").str.to_lowercase().is_in(NON_ELIGIBLE_RE_TYPES)

    # --- Annotate collateral with LGD categories (using shared expressions) ---
    # Ensure the AIRB-model flag is present (default False) so the pool-aware
    # aggregation below can rely on it. Backward-compatible with collateral
    # frames built before the column existed.
    if "is_airb_model_collateral" in collateral_schema.names():
        airb_flag_expr = pl.col("is_airb_model_collateral").fill_null(False)
    else:
        airb_flag_expr = pl.lit(False)

    annotated = adjusted_collateral.with_columns(
        [
            collateral_lgd_expr(resolved_pack).alias("collateral_lgd"),
            overcollateralisation_ratio_expr(resolved_pack).alias("overcollateralisation_ratio"),
            is_financial_collateral_type_expr().alias("is_financial_collateral_type"),
            collateral_category_expr().alias("_coll_category"),
            airb_flag_expr.alias("_is_airb_model_collateral"),
            pl.coalesce(
                pl.col("value_after_maturity_adj")
                if "value_after_maturity_adj" in collateral_schema.names()
                else pl.lit(None),
                pl.col("value_after_haircut")
                if "value_after_haircut" in collateral_schema.names()
                else pl.lit(None),
                pl.col("market_value"),
            ).alias("adjusted_value"),
        ]
    )
    annotated = annotated.with_columns(
        (pl.col("adjusted_value") / pl.col("overcollateralisation_ratio")).alias(
            "effectively_secured"
        ),
    )

    # CRR/PS1-26 Art. 199(2)/(5)/(6): FIRB Foundation Collateral Method non-
    # financial collateral (real estate, receivables, other physical) is
    # recognised on the LGD*-substitution path only where the institution ATTESTS
    # eligibility via the pre-existing ``is_eligible_irb_collateral`` flag. Default
    # False => ineligible — the flag IS the attestation, so the P1.10 new-field
    # null-permissive precedent does NOT apply. Art. 199(5): a receivable whose
    # ORIGINAL maturity is populated > 1 year is ineligible even if attested
    # (explicit data contradicting the attestation wins conservatively); a NULL
    # original maturity is PERMISSIVE (recorded deviation — the attestation covers
    # the maturity condition, absence doesn't contradict it). Ineligible rows are
    # zeroed on ``effectively_secured`` (the Art. 231 waterfall feed) with one
    # CRM014 warning each. Scope: FIRB FCM non-financial only — financial
    # collateral (Art. 197), SA EAD reduction, and exposure classification are
    # untouched.
    _non_financial = ~pl.col("is_financial_collateral_type")
    _attested = (
        pl.col("is_eligible_irb_collateral").fill_null(False)
        if "is_eligible_irb_collateral" in collateral_schema.names()
        else pl.lit(False)
    )
    _not_attested = _non_financial & ~_attested
    if "original_maturity_years" in collateral_schema.names():
        # NULL original maturity is PERMISSIVE (recorded deviation — the
        # attestation covers the maturity condition, absence doesn't contradict
        # it), so fill the *Boolean* > 1y test to False rather than the float
        # column to 0.0 (the latter would be an anti-conservative float fill).
        _receivables_too_long = (pl.col("_coll_category") == "receivables") & (
            pl.col("original_maturity_years") > 1.0
        ).fill_null(False)
    else:
        _receivables_too_long = pl.lit(False)
    if errors is not None:
        _record_ineligible_irb_collateral(annotated, _not_attested, _receivables_too_long, errors)
    annotated = annotated.with_columns(
        pl.when(_not_attested | _receivables_too_long)
        .then(pl.lit(0.0))
        .otherwise(pl.col("effectively_secured"))
        .alias("effectively_secured")
    )

    # --- Single group_by: EAD + LGD aggregates in one pass, split by AIRB pool ---
    # Each metric is split into a non-AIRB-pool variant (suffix ``_n``,
    # collateral with is_airb_model_collateral=False) and an AIRB-pool variant
    # (suffix ``_a``, collateral with is_airb_model_collateral=True). The two
    # variants are pro-rata-allocated against disjoint exposure pools so that
    # collateral incorporated in the AIRB internal LGD model never reaches
    # non-AIRB exposures (CRR Art. 181 / Basel 3.1 Art. 169A).
    val_expr = pl.coalesce(
        pl.col("value_after_maturity_adj"),
        pl.col("value_after_haircut"),
    )
    is_fin = pl.col("is_financial_collateral_type")
    cat = pl.col("_coll_category")
    is_flagged = pl.col("_is_airb_model_collateral")
    is_unflagged = ~is_flagged

    def _split_aggs(base_alias: str, value: pl.Expr, value_filter: pl.Expr) -> list[pl.Expr]:
        return [
            value.filter(value_filter & is_unflagged).sum().alias(f"{base_alias}_n"),
            value.filter(value_filter & is_flagged).sum().alias(f"{base_alias}_a"),
        ]

    # Build per-category effectively_secured aggregates for Art. 231 waterfall
    waterfall_aggs: list[pl.Expr] = []
    for cat_values, _lgds_key, suffix in WATERFALL_ORDER:
        waterfall_aggs.extend(
            _split_aggs(f"_e{suffix}", pl.col("effectively_secured"), cat.is_in(cat_values))
        )

    all_coll = (
        annotated.with_columns(
            beneficiary_level_expr().alias("_level"),
        )
        .group_by(["_level", "beneficiary_reference"])
        .agg(
            _split_aggs("_cv", val_expr, is_eligible)
            + _split_aggs("_mv", pl.col("market_value"), is_eligible)
            + _split_aggs("_rn", pl.col("adjusted_value"), ~is_fin)
            + _split_aggs("_adj_fin", pl.col("adjusted_value"), cat == "financial")
            + _split_aggs("_adj_cash", pl.col("adjusted_value"), cat == "cash")
            + _split_aggs("_adj_re", pl.col("adjusted_value"), cat == "real_estate")
            + _split_aggs("_adj_rec", pl.col("adjusted_value"), cat == "receivables")
            + _split_aggs("_adj_oth", pl.col("adjusted_value"), cat == "other_physical")
            + waterfall_aggs
        )
    )

    _wf_suffixes = [suffix for _, _, suffix in WATERFALL_ORDER]
    _metrics = [
        "_cv",
        "_mv",
        "_rn",
        "_adj_fin",
        "_adj_cash",
        "_adj_re",
        "_adj_rec",
        "_adj_oth",
    ] + [f"_e{s}" for s in _wf_suffixes]
    # Each metric has both _n (non-AIRB pool) and _a (AIRB pool) variants in the
    # aggregated frame; the level suffix (_d/_f/_c) is appended on rename below.
    _agg = [f"{m}_{p}" for m in _metrics for p in ("n", "a")]

    # Split the small aggregated result for per-level joins
    coll_direct = (
        all_coll.filter(pl.col("_level") == "direct")
        .drop("_level")
        .rename({c: f"{c}_d" for c in _agg})
    )
    coll_facility = (
        all_coll.filter(pl.col("_level") == "facility")
        .drop("_level")
        .rename({c: f"{c}_f" for c in _agg})
    )
    coll_counterparty = (
        all_coll.filter(pl.col("_level") == "counterparty")
        .drop("_level")
        .rename({c: f"{c}_c" for c in _agg})
    )

    # --- Join direct + counterparty levels to exposures ---
    exposures = exposures.join(
        coll_direct,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    )

    # Facility level: cascade collateral over each exposure's full ancestor set
    # so a pledge at any ancestor facility (parent, grandparent, ... root) flows
    # pro-rata to every descendant exposure (CRR Art. 230-231 pooling over the
    # facility subtree). Produces pre-weighted, ancestor-summed ``{m}_{p}_f``
    # columns that ``_sum6`` adds in directly (the pro-rata weight is already
    # baked in, so no further ``_fw`` multiply is needed).
    exposures = _cascade_facility_collateral(exposures, coll_facility, _metrics)

    exposures = exposures.join(
        coll_counterparty,
        left_on="counterparty_reference",
        right_on="beneficiary_reference",
        how="left",
    ).join(
        cp_ead_totals,
        on="counterparty_reference",
        how="left",
    )

    # --- Fill nulls + counterparty pro-rata weights ---
    # Facility ``{c}_f`` columns are already filled + pre-weighted by
    # ``_cascade_facility_collateral``; only the direct (``_d``) and
    # counterparty (``_c``) families plus the CP EAD totals need filling here.
    fill_exprs = []
    for sfx in ["d", "c"]:
        for c in _agg:
            fill_exprs.append(pl.col(f"{c}_{sfx}").fill_null(0.0))
    fill_exprs.extend(
        [
            pl.col("_cp_ead_total").fill_null(0.0),
            pl.col("_cp_ead_total_airb").fill_null(0.0),
            pl.col("_cp_ead_total_non_airb").fill_null(0.0),
        ]
    )
    exposures = exposures.with_columns(fill_exprs)

    # Pool-aware counterparty pro-rata weights. ``_is_airb_pool`` was tagged on
    # exposures in ``apply_collateral`` via ``airb_lgd_preserved_expr``; weights
    # bake in the pool-match gate so non-matching pools always contribute zero.
    in_airb = pl.col("_is_airb_pool").fill_null(False)
    in_non_airb = ~in_airb
    # Pro-rata weights use ead_for_crm (CRR Art. 223(4) / PS1/26 Art. 223(4):
    # off-BS items at CCF=100% for CRM allocation purposes), so the share
    # an exposure receives of a CP collateral pool is proportional to its full
    # pre-CCF basis rather than its post-CCF EAD.
    exposures = exposures.with_columns(
        [
            pl.when(in_non_airb & (pl.col("_cp_ead_total_non_airb") > 0))
            .then(pl.col("ead_for_crm") / pl.col("_cp_ead_total_non_airb"))
            .otherwise(pl.lit(0.0))
            .alias("_cw_n"),
            pl.when(in_airb & (pl.col("_cp_ead_total_airb") > 0))
            .then(pl.col("ead_for_crm") / pl.col("_cp_ead_total_airb"))
            .otherwise(pl.lit(0.0))
            .alias("_cw_a"),
            in_airb.cast(pl.Float64).alias("_airb_match"),
        ]
    )

    # --- Combine all levels for EAD + LGD ---
    # Non-AIRB-flagged collateral (``_n`` family) flows to non-AIRB-pool
    # exposures: facility via the ancestor cascade (``_n_f`` pre-weighted) and
    # counterparty via the ``_cw_n`` weight (both gated to that pool); direct
    # unflagged is unconditional (1:1, no pro-rata). AIRB-flagged collateral
    # (``_a`` family) flows only to AIRB-pool exposures — facility via the
    # cascade (``_a_f``), counterparty via ``_cw_a``, and direct gated by
    # ``_airb_match``. Direct flagged collateral on a non-AIRB exposure is a
    # data-quality issue surfaced as CRM006 by the validation pass.
    def _sum6(metric: str) -> pl.Expr:
        # Facility terms (``_f``) are already pro-rata-weighted and summed over
        # the exposure's ancestor facilities by ``_cascade_facility_collateral``,
        # so they enter the blend without a further weight multiply.
        return (
            pl.col(f"{metric}_n_d")
            + pl.col(f"{metric}_a_d") * pl.col("_airb_match")
            + pl.col(f"{metric}_n_f")
            + pl.col(f"{metric}_a_f")
            + pl.col(f"{metric}_n_c") * pl.col("_cw_n")
            + pl.col(f"{metric}_a_c") * pl.col("_cw_a")
        )

    combine_exprs = [
        _sum6("_cv").alias("collateral_adjusted_value"),
        _sum6("_mv").alias("collateral_market_value"),
        _sum6("_adj_fin").alias("collateral_financial_value"),
        _sum6("_adj_cash").alias("collateral_cash_value"),
        _sum6("_adj_re").alias("collateral_re_value"),
        _sum6("_adj_rec").alias("collateral_receivables_value"),
        _sum6("_adj_oth").alias("collateral_other_physical_value"),
        _sum6("_rn").alias("_raw_nf_a"),
    ]
    # Per-category effectively_secured after multi-level combination
    for suffix in _wf_suffixes:
        combine_exprs.append(_sum6(f"_e{suffix}").alias(f"_eff_{suffix}_a"))
    exposures = exposures.with_columns(combine_exprs)

    # Per-type minimum collateralisation thresholds (CRR Art. 230)
    # Art. 230 requires the threshold to apply per collateral type, not across
    # the combined non-financial pool.  Each type (real_estate, other_physical)
    # must independently meet its 30% threshold to be eligible for LGDS
    # reduction.  Financial, covered_bond, and receivables have no threshold.
    #
    # PS1/26 Art. 230(1) replaces the CRR step-function with a continuous LGD*
    # formula and removes the C* / C** thresholds entirely — under Basel 3.1
    # any positive eligible non-financial collateral is recognised at LGDS.
    if resolved_pack.feature("firb_min_collateralisation_threshold_applies"):
        _min_thresholds = lookup_float_map(resolved_pack.lookup("min_collateralisation_thresholds"))
        _type_threshold: dict[str, tuple[float, str]] = {
            "re": (_min_thresholds["real_estate"], "collateral_re_value"),
            "op": (
                _min_thresholds["other_physical"],
                "collateral_other_physical_value",
            ),
        }
        nf_threshold_exprs = []
        for suffix in _wf_suffixes:
            if suffix not in _type_threshold:
                continue  # No threshold for fin/cb/rec
            threshold, raw_col = _type_threshold[suffix]
            if threshold <= 0:
                continue
            col_name = f"_eff_{suffix}_a"
            # Art. 230 minimum-collateralisation threshold uses E with CCF=100%
            # per Art. 223(4) — the threshold is a fraction of the pre-CCF basis.
            nf_threshold_exprs.append(
                pl.when(pl.col(raw_col) >= threshold * pl.col("ead_for_crm"))
                .then(pl.col(col_name))
                .otherwise(pl.lit(0.0))
                .alias(col_name)
            )
        if nf_threshold_exprs:
            exposures = exposures.with_columns(nf_threshold_exprs)

    # --- Art. 231 sequential fill (waterfall) ---
    # Allocate from lowest LGDS to highest. Each category absorbs up to
    # min(category_total, remaining_exposure). Uses the cumulative-cap
    # trick: es_i = min(cum_through_i, EAD) - min(cum_through_i-1, EAD).
    # EAD here is ead_for_crm (CCF=100% basis per Art. 223(4)) — the
    # actual post-CCF EAD is recoupled later for SA via effective_ccf.
    ead = pl.col("ead_for_crm")
    cum = pl.lit(0.0)
    es_exprs: list[pl.Expr] = []
    for suffix in _wf_suffixes:
        prev_cum = cum
        cum = cum + pl.col(f"_eff_{suffix}_a")
        es_i = pl.min_horizontal(cum, ead) - pl.min_horizontal(prev_cum, ead)
        es_exprs.append(es_i.alias(f"_es_{suffix}"))

    total_secured_expr = pl.min_horizontal(cum, ead)

    # Blended lgd_secured = sum(lgds_i * es_i) / total_secured
    # CRR Art. 230 Table 5: subordinated exposures use higher LGDS for the
    # secured portion (receivables 65%, RE 65%, other physical 70%).
    # Basel 3.1 Art. 230(2) removes the subordinated LGDS column entirely.
    _has_seniority = "seniority" in exposure_schema.names()
    _build_sub = overcollateralisation_step_function and _has_seniority

    lgd_num = pl.lit(0.0)
    lgd_num_sub = pl.lit(0.0) if _build_sub else None
    for _, lgds_key, suffix in WATERFALL_ORDER:
        es_col = pl.col(f"_es_{suffix}")
        lgd_num = lgd_num + pl.lit(lgds[lgds_key]) * es_col
        if _build_sub:
            sub_lgds = lgd_values.get(f"{lgds_key}_subordinated", lgd_values[lgds_key])
            lgd_num_sub = lgd_num_sub + pl.lit(sub_lgds) * es_col

    if _build_sub:
        is_sub = (
            pl.col("seniority").fill_null("").str.to_lowercase().is_in(["subordinated", "junior"])
        )
        lgd_num_final = pl.when(is_sub).then(lgd_num_sub).otherwise(lgd_num)
    else:
        lgd_num_final = lgd_num

    # Compute sequential allocations, then total + lgd_secured
    exposures = exposures.with_columns(es_exprs)
    exposures = exposures.with_columns(
        [
            total_secured_expr.alias("total_collateral_for_lgd"),
            pl.when(total_secured_expr > 0)
            .then(lgd_num_final / total_secured_expr)
            .otherwise(pl.lit(lgd_unsecured))
            .alias("lgd_secured"),
        ]
    )

    # --- Drop intermediate allocation columns ---
    # Preserve _es_* columns (renamed to crm_alloc_*) for the A-IRB blended
    # LGD floor (Art. 164(4)(c)).  These encode the dollar amount of EAD
    # absorbed by each collateral category in the Art. 231 waterfall.
    drop_cols = (
        [f"{c}_{sfx}" for sfx in ["d", "f", "c"] for c in _agg]
        + [
            "_cp_ead_total",
            "_cp_ead_total_airb",
            "_cp_ead_total_non_airb",
            "_cw_n",
            "_cw_a",
            "_airb_match",
            "_is_airb_pool",
            "_raw_nf_a",
        ]
        + [f"_eff_{s}_a" for s in _wf_suffixes]
    )
    exposures = exposures.drop(drop_cols)
    exposures = exposures.rename({f"_es_{s}": CRM_ALLOC_COLUMNS[s] for s in _wf_suffixes})

    # --- Apply EAD reduction + determine seniority-based LGDU ---
    # Supervisory LGDU for unsecured portion: FSE-aware under Basel 3.1
    # (Art. 161(1)(a) vs (aa))
    if _has_fse_col:
        supervisory_lgdu_expr = (
            pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
            .then(pl.lit(lgd_unsecured_fse))
            .otherwise(pl.lit(lgd_unsecured))
        )
    else:
        supervisory_lgdu_expr = pl.lit(lgd_unsecured)

    # --- Determine which AIRB exposures use the Foundation formula ---
    # Art. 169A/169B (Basel 3.1 only): AIRB exposures may use the Foundation
    # Collateral Method formula under two scenarios:
    #   (1) Foundation election: firm opts for FCM instead of LGD Modelling
    #   (2) Art. 169B fallback: insufficient data → FCM formula with own LGDU
    # Under CRR, AIRB is free-form — own LGD always kept unchanged.
    exposure_schema = exposures.collect_schema()
    _has_lgd_unsecured_col = "lgd_unsecured" in exposure_schema.names()
    schema_names = set(exposure_schema.names())

    airb_method = config.airb_collateral_method
    is_airb = pl.col("approach") == ApproachType.AIRB.value

    # ``_airb_uses_formula`` is the negation of the LGD-preserved condition:
    # AIRB rows that fall back to the supervisory formula under Foundation
    # election or Art. 169B insufficient-data fallback.
    _airb_uses_formula = is_airb & ~airb_lgd_preserved_expr(
        config, schema_names, pack=resolved_pack
    )
    # Art. 169B(2)(c): use firm's own unsecured LGD when LGD-modelling falls back
    _airb_own_lgdu = (
        airb_collateral_method_applies and airb_method == AIRBCollateralMethod.LGD_MODELLING
    )

    # Combined condition: FIRB OR qualifying AIRB exposures use the formula
    _uses_formula = (pl.col("approach") == ApproachType.FIRB.value) | _airb_uses_formula

    # Build per-exposure LGDU expression
    # For AIRB Art. 169B: LGDU = own lgd_unsecured (Art. 169B(2)(c))
    # For FIRB and AIRB Foundation: LGDU = supervisory value
    is_subordinated = pl.col("seniority").str.to_lowercase().is_in(["subordinated", "junior"])

    if _airb_own_lgdu and _has_lgd_unsecured_col:
        # Art. 169B: AIRB exposures with insufficient data use own lgd_unsecured,
        # falling back to lgd_pre_crm if lgd_unsecured not provided.
        own_lgdu = pl.coalesce(pl.col("lgd_unsecured"), pl.col("lgd_pre_crm"))
        lgdu_expr = (
            pl.when(is_subordinated)
            .then(pl.lit(lgd_subordinated))
            .when(_airb_uses_formula)
            .then(own_lgdu)
            .otherwise(supervisory_lgdu_expr)
        )
    else:
        lgdu_expr = (
            pl.when(is_subordinated).then(pl.lit(lgd_subordinated)).otherwise(supervisory_lgdu_expr)
        )

    # SA EAD reduction (CRR Art. 228(1) / PS1/26 Art. 228(1)) with the
    # CRR Art. 223(5) FCCM exposure-side gross-up:
    #   E*  = max(0, ead_for_crm × (1 + HE) − collateral_adjusted_value)
    #   EAD = E* × CCF_actual   (i.e. × effective_ccf for blended rows)
    # The CCF is applied to E*, not to the pre-collateral nominal — this is
    # the regulatorily mandated ordering and reverses the previous
    # implementation (which netted collateral against post-CCF ead_gross).
    # FIRB / Slotting / AIRB keep ead_gross because under those approaches
    # collateral modifies LGD (via lgd_post_crm), not EAD.
    schema_for_he = exposures.collect_schema().names()
    if "exposure_volatility_haircut" in schema_for_he:
        he_factor = pl.lit(1.0) + pl.col("exposure_volatility_haircut").fill_null(0.0)
    else:
        he_factor = pl.lit(1.0)
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then(
                (pl.col("ead_for_crm") * he_factor - pl.col("collateral_adjusted_value")).clip(
                    lower_bound=0
                )
                * pl.col("effective_ccf")
            )
            .otherwise(pl.col("ead_gross"))
            .alias("ead_after_collateral"),
            lgdu_expr.alias("lgd_unsecured"),
        ]
    )

    # --- Calculate LGD post-CRM + audit ---
    # LGD* formula (Art. 230/231) applies to FIRB and qualifying AIRB exposures.
    # Non-qualifying AIRB and SA keep lgd_pre_crm.
    #
    # CRR Art. 223(4) / PS1/26 Art. 223(4): the exposure value E used in the
    # LGD* formula is the CCF=100% basis (ead_for_crm) for off-balance-sheet
    # items, NOT the post-CCF EAD.  For pure on-BS rows ead_for_crm == ead_gross.
    #
    # PS1/26 Art. 230(1) / CRR Art. 228(2) (P1.272): the exposure basis is
    # grossed up by its own volatility haircut HE — E' = E(1 + HE) — so
    #   LGD* = (LGDS · min(C, E') + LGDU · max(0, E' - C)) / E'.
    # HE (exposure_volatility_haircut, Art. 223(5)) is non-zero only for SFT rows
    # lending out a debt security, so he_factor == 1 for every other row and
    # E' == E; the SFT-FCCM path is unaffected (it emits E* directly).
    e_for_lgd_star = pl.col("ead_for_crm") * he_factor
    lgd_star_expr = (
        (
            pl.col("lgd_secured")
            * pl.col("total_collateral_for_lgd").clip(upper_bound=e_for_lgd_star)
        )
        + (
            pl.col("lgd_unsecured")
            * (e_for_lgd_star - pl.col("total_collateral_for_lgd")).clip(lower_bound=0)
        )
    ) / e_for_lgd_star

    exposures = exposures.with_columns(
        [
            pl.when(
                _uses_formula
                & (pl.col("ead_for_crm") > 0)
                & (pl.col("total_collateral_for_lgd") > 0)
            )
            .then(lgd_star_expr)
            .when(_uses_formula & (pl.col("ead_for_crm") > 0))
            .then(pl.col("lgd_unsecured"))
            .otherwise(pl.col("lgd_pre_crm"))
            .alias("lgd_post_crm"),
            # collateral_coverage_pct is the C/E ratio used for the Art. 230
            # threshold tests, so it also uses ead_for_crm.
            pl.when(pl.col("ead_for_crm") > 0)
            .then(
                pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_for_crm"))
                / pl.col("ead_for_crm")
                * 100
            )
            .otherwise(pl.lit(0.0))
            .alias("collateral_coverage_pct"),
        ]
    )

    return exposures


def _cascade_facility_collateral(
    exposures: pl.LazyFrame,
    coll_facility: pl.LazyFrame,
    metrics: list[str],
) -> pl.LazyFrame:
    """Distribute facility-level collateral over each exposure's ancestor set.

    Supports nested facility hierarchies: collateral pledged at *any* ancestor
    facility ``F`` (immediate parent, grandparent, ... root) flows pro-rata to
    every descendant exposure, shared by ``ead_for_crm`` across ``F``'s whole
    subtree (CRR Art. 230-231 pooling). Membership comes from the
    ``ancestor_facilities`` list column (parent + all ancestors incl. self).

    For every (exposure, ancestor facility) pair the exposure receives
    ``ead_for_crm / subtree_ead[F, pool]`` of ``F``'s pooled facility
    collateral; contributions are summed across ancestor levels, so a pledge at
    the grandparent and one at the direct parent stack. Pool-aware: the
    non-AIRB subtree denominator applies to non-AIRB-pool exposures and the AIRB
    denominator to AIRB-pool exposures, so unflagged collateral never leaks into
    the AIRB pool (CRR Art. 181 / Basel 3.1 Art. 169A).

    Returns ``exposures`` with one ``{metric}_n_f`` and ``{metric}_a_f`` column
    per metric, each already pro-rata-weighted and ancestor-summed (so ``_sum6``
    adds them in without a further weight multiply). Reduces exactly to the
    legacy single-level allocation when every ``ancestor_facilities`` is its
    ``[parent]``.
    """
    agg_cols = [f"{m}_{p}_f" for m in metrics for p in ("n", "a")]

    # (exposure, ancestor facility) edge list with pool flag + EAD basis.
    edges = (
        exposures.select(
            "exposure_reference",
            "ead_for_crm",
            pl.col("_is_airb_pool").fill_null(False).alias("_pool"),
            "ancestor_facilities",
        )
        .explode("ancestor_facilities")
        .rename({"ancestor_facilities": "_anc_fac"})
        .filter(pl.col("_anc_fac").is_not_null())
    )

    # Pool-aware subtree EAD per ancestor facility (over ALL descendant exposures).
    subtree = edges.group_by("_anc_fac").agg(
        pl.col("ead_for_crm").filter(pl.col("_pool")).sum().alias("_sub_airb"),
        pl.col("ead_for_crm").filter(~pl.col("_pool")).sum().alias("_sub_non_airb"),
    )

    contrib = (
        edges.join(
            coll_facility,
            left_on="_anc_fac",
            right_on="beneficiary_reference",
            how="inner",
        )
        .join(subtree, on="_anc_fac", how="left")
        .with_columns(
            pl.when(~pl.col("_pool") & (pl.col("_sub_non_airb") > 0))
            .then(pl.col("ead_for_crm") / pl.col("_sub_non_airb"))
            .otherwise(pl.lit(0.0))
            .alias("_w_n"),
            pl.when(pl.col("_pool") & (pl.col("_sub_airb") > 0))
            .then(pl.col("ead_for_crm") / pl.col("_sub_airb"))
            .otherwise(pl.lit(0.0))
            .alias("_w_a"),
        )
        .with_columns(
            [(pl.col(f"{m}_n_f") * pl.col("_w_n")).alias(f"{m}_n_f") for m in metrics]
            + [(pl.col(f"{m}_a_f") * pl.col("_w_a")).alias(f"{m}_a_f") for m in metrics]
        )
        .group_by("exposure_reference")
        .agg([pl.col(c).sum() for c in agg_cols])
    )

    return exposures.join(contrib, on="exposure_reference", how="left").with_columns(
        [pl.col(c).fill_null(0.0) for c in agg_cols]
    )
