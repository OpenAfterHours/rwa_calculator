"""
Standardised Approach post-base risk-weight adjustments.

Plain typed functions applied after the base SA risk-weight assignment, in
regulatory order: Art. 222 FCSM substitution, Art. 232 life-insurance
mapping, Art. 213-217 guarantee substitution, the Basel 3.1 Art. 123B
currency-mismatch multiplier, and the Basel 3.1 Art. 110A due-diligence
override. ``SACalculator`` composes them via ``LazyFrame.pipe``.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- Art. 222 Financial Collateral Simple Method RW substitution
- Art. 232 life-insurance collateral RW mapping
- Art. 213-217 unfunded credit protection (guarantee substitution)
- PRA PS1/26 Art. 123B currency-mismatch multiplier (Basel 3.1)
- PRA PS1/26 Art. 110A due-diligence override (Basel 3.1)

References:
- CRR Art. 213-217: Unfunded credit protection (guarantee substitution)
- CRR Art. 222: Financial Collateral Simple Method
- CRR Art. 232: Life insurance collateral
- PRA PS1/26 Art. 110A: Basel 3.1 due diligence override
- PRA PS1/26 Art. 123B: Basel 3.1 currency mismatch multiplier
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    denomination_currency_expr,
)
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr
from rwa_calc.engine.sa.risk_weights import _SA_B31_RW
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# PRA PS1/26 Basel 3.1 commencement date, resolved from the b31 pack once at
# module load. Reporting dates strictly before this fall under pre-Basel-3.1
# treatment (the Art. 123B currency-mismatch multiplier this gates does not
# apply). Raw date compared date-to-date (no coercion). (S13-g)
_B31_PACK = resolve("b31", date(2027, 1, 1))
_B31_EFFECTIVE_DATE = _B31_PACK.date_param("b31_effective_date").value


@cites("CRR Art. 222")
def apply_fcsm_rw_substitution(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply Art. 222 Financial Collateral Simple Method risk weight substitution.

    When the Simple Method is elected, the secured portion of each SA exposure
    gets the collateral's SA risk weight instead of the exposure's own risk
    weight. The unsecured portion retains the original RW.

    Blended RW = secured_pct × collateral_rw + unsecured_pct × exposure_rw

    The 20% floor (Art. 222(1)/(3)) and same-currency 0% carve-outs (CRR
    Art. 222(4) / PRA PS1/26 Art. 222(6)) are applied per item in
    ``compute_fcsm_columns``. Applying the floor again on the aggregate would
    re-impose it on carve-out items — contrary to "except as specified in
    paragraphs 4 to 6".

    This function is a no-op when the Comprehensive Method is elected (default)
    or when fcsm_collateral_value is zero/null — the crm_exit contract
    injects both fcsm_* columns as typed nulls when the FCSM sub-step did
    not run, and ``fill_null(0.0)`` makes an all-null column equivalent to
    the historical absent-column early return.
    """
    if config.crm_collateral_method != CRMCollateralMethod.SIMPLE:
        return lf

    ead = pl.col("ead_final").fill_null(0.0)
    fcsm_value = pl.col("fcsm_collateral_value").fill_null(0.0)
    fcsm_rw = pl.col("fcsm_collateral_rw").fill_null(0.0)

    # Secured percentage (capped at 100%)
    secured_pct = pl.when(ead > 0).then((fcsm_value / ead).clip(0.0, 1.0)).otherwise(0.0)
    unsecured_pct = pl.lit(1.0) - secured_pct

    # Blended risk weight; secured RW already reflects per-item floor + carve-outs.
    blended_rw = secured_pct * fcsm_rw + unsecured_pct * pl.col("risk_weight")

    # Only apply when there is actual collateral value
    has_fcsm = fcsm_value > 0

    return lf.with_columns(
        # Save pre-FCSM risk weight for audit
        pl.col("risk_weight").alias("pre_fcsm_risk_weight"),
        # Apply blended RW
        pl.when(has_fcsm).then(blended_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
        # Track method for audit/COREP
        pl.when(has_fcsm)
        .then(pl.lit("simple"))
        .otherwise(pl.lit("comprehensive"))
        .alias("ead_calculation_method"),
    )


@cites("CRR Art. 232")
def apply_life_insurance_rw_mapping(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Apply Art. 232 life insurance risk weight mapping for SA exposures.

    When life insurance collateral secures an exposure, the secured portion
    receives a mapped risk weight (not direct substitution):
        Insurer RW 20%           -> 20%
        Insurer RW 30% or 50%    -> 35%
        Insurer RW 65%-135%      -> 70%
        Insurer RW 150%          -> 150%

    Blended RW = secured_pct x mapped_rw + unsecured_pct x exposure_rw

    This function is a no-op when no life insurance collateral is present.
    """
    ead = pl.col("ead_final").fill_null(0.0)
    li_value = pl.col("life_ins_collateral_value").fill_null(0.0)
    li_rw = pl.col("life_ins_secured_rw").fill_null(0.0)

    # Secured percentage (capped at 100%)
    secured_pct = pl.when(ead > 0).then((li_value / ead).clip(0.0, 1.0)).otherwise(0.0)
    unsecured_pct = pl.lit(1.0) - secured_pct

    # Blended risk weight: no floor — Art. 232 has no 20% floor like FCSM
    blended_rw = secured_pct * li_rw + unsecured_pct * pl.col("risk_weight")

    # Only apply when there is actual life insurance collateral
    has_li = li_value > 0

    return lf.with_columns(
        pl.when(has_li).then(blended_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
    )


@cites("CRR Art. 213")
def apply_guarantee_substitution(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply guarantee substitution for unfunded credit protection.

    For guaranteed portions, the risk weight is substituted with the
    guarantor's risk weight. The final RWA is calculated using blended
    risk weight based on guaranteed vs unguaranteed portions.

    CRR Art. 213-217: Unfunded credit protection.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    exposures = lf
    cols = exposures.collect_schema().names()

    # Run-level sentinel gate: guarantor_entity_type is the one crm_exit
    # column still CONDITIONAL (inject=False) — present iff the CRM
    # guarantee sub-step ran. Keying on it keeps this machinery (and its
    # derived audit columns: pre_crm_risk_weight, guarantor_rw,
    # is_guarantee_beneficial, guarantee_status, guarantee_benefit_rw)
    # off unguaranteed runs; see contracts/edges.py. The
    # guaranteed_portion check covers direct (non-pipeline) invocation.
    if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
        return exposures

    # Ensure defensive column fallbacks (guarantor_exposure_class,
    # guarantor_country_code, guarantor_is_ccp_client_cleared). In
    # production these are set by the CRM processor; this fallback covers
    # tests that construct LazyFrames directly and skip the CRM stage.
    exposures = _ensure_guarantee_substitution_columns(exposures)

    # Preserve pre-CRM risk weight for regulatory reporting (pre-CRM vs
    # post-CRM views).
    exposures = exposures.with_columns(
        pl.col("risk_weight").alias("pre_crm_risk_weight"),
    )

    # Art. 114(4)/(7) domestic CGCB-guarantor currency check.
    is_domestic_guarantor = _build_domestic_guarantor_expr(exposures.collect_schema().names())

    # CRR/PS1/26 Art. 120(2) Table 4 short-term institution guarantor flag.
    # The substituted exposure's original maturity (≤ 3 months / 0.25y)
    # drives the short-term carve-out — same convention as the direct
    # institution short-term branches in ``risk_weights.py`` (Art. 120(2),
    # Art. 121(3)). ``original_maturity_years`` is derived earlier in
    # ``apply_risk_weights`` from (maturity_date - value_date) when absent,
    # so it is always populated here.
    short_term_flag_col = "_inst_guarantor_short_term"
    if "original_maturity_years" in exposures.collect_schema().names():
        short_term_expr = pl.col("original_maturity_years").is_not_null() & (
            pl.col("original_maturity_years") <= 0.25
        )
    else:
        short_term_expr = pl.lit(False)
    exposures = exposures.with_columns(
        short_term_expr.fill_null(False).alias(short_term_flag_col),
    )

    # Look up guarantor's RW based on exposure class + CQS. The short-term
    # flag is calculator scratch consumed only by this expression — drop it
    # immediately so it never leaks into the branch/aggregator frames.
    exposures = exposures.with_columns(
        _build_guarantor_rw_expr(
            is_domestic_guarantor,
            resolved_pack.feature("sa_revised_risk_weight_tables"),
            institution_short_term_flag_col=short_term_flag_col,
        ).alias("guarantor_rw"),
    ).drop(short_term_flag_col)

    # Check if guarantee is beneficial (guarantor RW < borrower RW)
    # Non-beneficial guarantees should NOT be applied per CRR Art. 213
    exposures = exposures.with_columns(
        [
            pl.when(
                (pl.col("guaranteed_portion") > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("guarantor_rw") < pl.col("pre_crm_risk_weight"))
            )
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_guarantee_beneficial"),
        ]
    )

    # Redistribute non-beneficial guarantee portions to beneficial guarantors.
    # For multi-guarantor exposures, non-beneficial guarantors' EAD is reallocated
    # to the most beneficial (lowest RW) guarantors using greedy fill.
    from rwa_calc.engine.crm.guarantees import redistribute_non_beneficial

    exposures = redistribute_non_beneficial(exposures)

    # Calculate blended risk weight using substitution approach
    # Only apply if guarantee is beneficial
    # RWA = (unguaranteed_portion * borrower_rw + guaranteed_portion * guarantor_rw) / ead_final
    exposures = exposures.with_columns(
        [
            # Blended risk weight when guarantee exists AND is beneficial
            pl.when(
                (pl.col("guaranteed_portion") > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("is_guarantee_beneficial"))
            )
            .then(
                # weighted average of borrower and guarantor risk weights
                (
                    pl.col("unguaranteed_portion") * pl.col("pre_crm_risk_weight")
                    + pl.col("guaranteed_portion") * pl.col("guarantor_rw")
                )
                / pl.col("ead_final")
            )
            # No guarantee, no guarantor RW, or non-beneficial - use original risk weight
            .otherwise(pl.col("pre_crm_risk_weight"))
            .alias("risk_weight"),
        ]
    )

    # Track guarantee status for reporting
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("guaranteed_portion") <= 0)
            .then(pl.lit("NO_GUARANTEE"))
            .when(~pl.col("is_guarantee_beneficial"))
            .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
            .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
            .alias("guarantee_status"),
            # Calculate RW benefit from guarantee (positive = RW reduced)
            pl.when(pl.col("is_guarantee_beneficial"))
            .then(pl.col("pre_crm_risk_weight") - pl.col("risk_weight"))
            .otherwise(pl.lit(0.0))
            .alias("guarantee_benefit_rw"),
        ]
    )

    return exposures


@cites("PS1/26, paragraph 123B")
@cites("PS1/26, paragraph 123B.3")
def apply_currency_mismatch_multiplier(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply 1.5x RW multiplier for retail/RE currency mismatch (Basel 3.1 only).

    When the exposure currency differs from the borrower's income currency,
    a 1.5x multiplier is applied to the risk weight for retail and real estate
    exposure classes.

    Basel 3.1 Art. 123B / CRE20.93.

    Art. 123B(3) transitional: the multiplier is a Basel-3.1-only measure that
    commences on ``_B31_EFFECTIVE_DATE`` (1 January 2027). Reporting dates strictly
    before that fall under the pre-Basel-3.1 portfolio treatment and the frame is
    returned unchanged. The boundary date 1 January 2027 is in scope (strict ``<``).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_currency_mismatch_multiplier"):
        return lf

    # Art. 123B(3) transitional: pre-commencement reporting dates suppress the
    # multiplier entirely. Emit the reporting column as ``False`` (consistent with
    # the no-mismatch branch below) so downstream reporting always sees the flag.
    if config.reporting_date < _B31_EFFECTIVE_DATE:
        return lf.with_columns(pl.lit(False).alias("currency_mismatch_multiplier_applied"))

    schema = lf.collect_schema()
    cols = schema.names()

    # Need both exposure currency and borrower income currency
    income_col = (
        "cp_borrower_income_currency"
        if "cp_borrower_income_currency" in cols
        else "borrower_income_currency"
        if "borrower_income_currency" in cols
        else None
    )
    if income_col is None or "currency" not in cols:
        return lf

    # PRA PS1/26 Art. 123B: the 1.5x currency-mismatch multiplier is in scope
    # ONLY for retail (Art. 112(h)) and residential RE (Art. 112(i)) exposures.
    # Commercial RE (Art. 112(j) per Art. 124H/124I) and corporate are OUT of
    # scope. Use exact-match against ExposureClass enum string values rather
    # than substring matching to avoid COMMERCIAL_MORTGAGE matching "COMMERCIAL".
    is_retail_or_re = (
        pl.col("exposure_class")
        .fill_null("")
        .is_in(
            [
                "retail_other",
                "retail_qrre",
                "retail_mortgage",
                "residential_mortgage",
            ]
        )
    )

    has_mismatch = pl.col(income_col).is_not_null() & (pl.col(income_col) != pl.col("currency"))

    # Art. 123B(2) / CRE20.93: the 1.5x mismatch multiplier is suppressed when
    # the exposure is hedged against currency risk. A full hedge can be signalled
    # either by ``is_hedged=True`` OR by ``hedge_coverage_ratio >= 0.90`` (the
    # Art. 123B(2) partial-hedge coverage floor). Both columns default to their
    # "no hedge" sentinel when missing or null (False / 0.0).
    is_hedged_flag = pl.col("is_hedged").fill_null(False) if "is_hedged" in cols else pl.lit(False)
    # Art. 123B(2A): for revolving facilities the 90%-coverage test denominator is
    # the fully-drawn committed amount (the "instalment amount" = greater of the
    # contractual minimum and the fully-drawn contractual amount; leg (b) here,
    # there being no contractual-minimum field). The firm-supplied
    # ``hedge_coverage_ratio`` measures coverage of the CURRENT drawn balance, so
    # for revolving rows it is rescaled onto the full-draw base:
    #     full_draw_base     = max(drawn_amount, facility_limit)
    #     effective_coverage = (hedge_coverage_ratio * drawn_amount) / full_draw_base
    # Non-revolving rows are unchanged (effective_coverage = hedge_coverage_ratio).
    # is_revolving / facility_limit / drawn_amount may be absent on production SA
    # frames — default safely so the rescale is a no-op and legacy behaviour holds.
    if "hedge_coverage_ratio" in cols:
        raw_coverage = pl.col("hedge_coverage_ratio").fill_null(0.0)
        is_revolving_flag = (
            pl.col("is_revolving").fill_null(False) if "is_revolving" in cols else pl.lit(False)
        )
        drawn_amount = (
            pl.col("drawn_amount").fill_null(0.0) if "drawn_amount" in cols else pl.lit(0.0)
        )
        # Absent facility_limit -> use drawn_amount so full_draw_base == drawn_amount
        # and the rescale collapses to the legacy coverage ratio.
        facility_limit = (
            pl.col("facility_limit").fill_null(drawn_amount)
            if "facility_limit" in cols
            else drawn_amount
        )
        full_draw_base = pl.max_horizontal(drawn_amount, facility_limit)
        effective_coverage = (
            pl.when(is_revolving_flag & (full_draw_base > 0.0))
            .then((raw_coverage * drawn_amount) / full_draw_base)
            .otherwise(raw_coverage)
        )
        hedge_coverage_ok = effective_coverage >= _SA_B31_RW["currency_mismatch_hedge_floor"]
    else:
        hedge_coverage_ok = pl.lit(False)
    waive_expr = is_hedged_flag | hedge_coverage_ok

    mismatch_applies = is_retail_or_re & has_mismatch & ~waive_expr

    return lf.with_columns(
        [
            # Snapshot pre-multiplier RW for audit/reporting (mirrors the
            # pre_fcsm_risk_weight pattern). For non-mismatch rows this equals
            # the unchanged risk_weight; CR5 buckets EAD on this column.
            pl.col("risk_weight").alias("risk_weight_pre_currency_mismatch"),
            pl.when(mismatch_applies)
            .then(
                (pl.col("risk_weight") * _SA_B31_RW["currency_mismatch_multiplier"]).clip(
                    upper_bound=pl.lit(_SA_B31_RW["currency_mismatch_cap"])
                )
            )
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            mismatch_applies.alias("currency_mismatch_multiplier_applied"),
        ]
    )


@cites("PS1/26, paragraph 110A")
def apply_due_diligence_override(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    errors: list[CalculationError] | None = None,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply due diligence risk weight override (Basel 3.1 Art. 110A).

    Under Basel 3.1, firms must perform due diligence on all SA exposures.
    Where due diligence reveals that the risk weight does not adequately
    reflect the risk, the firm must apply a higher risk weight.

    The override only increases the risk weight — it can never reduce it.
    This is applied as the final risk weight modification before RWA
    calculation, after all standard RW determination, CRM, and currency
    mismatch adjustments.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("sa_due_diligence_override"):
        return lf

    schema = lf.collect_schema()
    cols = schema.names()

    # Warn if due_diligence_performed column is absent under Basel 3.1
    if "due_diligence_performed" not in cols and errors is not None:
        errors.append(
            CalculationError(
                code=ERROR_DUE_DILIGENCE_NOT_PERFORMED,
                message=(
                    "Due diligence assessment status not provided "
                    "(due_diligence_performed column absent). "
                    "Art. 110A requires firms to perform due diligence "
                    "on all SA exposures to ensure risk weights "
                    "appropriately reflect exposure risk."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA_QUALITY,
                regulatory_reference="PRA PS1/26 Art. 110A",
                field_name="due_diligence_performed",
            )
        )

    # Apply override RW where provided and higher than calculated RW
    if "due_diligence_override_rw" not in cols:
        return lf

    override_applies = pl.col("due_diligence_override_rw").is_not_null() & (
        pl.col("due_diligence_override_rw") > pl.col("risk_weight")
    )

    return lf.with_columns(
        [
            pl.when(override_applies)
            .then(pl.col("due_diligence_override_rw"))
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            override_applies.alias("due_diligence_override_applied"),
        ]
    )


# ---------------------------------------------------------------------------
# Guarantee-substitution helpers (CRR Art. 213-217)
#
# The guarantee-substitution stage relies on a few columns that may be missing
# when the calculator is invoked directly from tests (i.e. bypassing the CRM
# processor). These helpers own the defensive preparation and the
# guarantor-RW when/then chain in one place.
# ---------------------------------------------------------------------------


def _ensure_guarantee_substitution_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Ensure optional guarantor columns exist before guarantee substitution.

    In production ``guarantor_exposure_class`` is set by the CRM processor
    (``engine/crm/guarantees.py``) from ``ENTITY_TYPE_TO_SA_CLASS``. This
    fallback covers unit tests that construct LazyFrames directly and skip
    the CRM stage.

    Adds (if absent):
        guarantor_exposure_class        — derived from guarantor_entity_type
        guarantor_country_code          — null String
        guarantor_is_ccp_client_cleared — null Boolean
        guarantor_scra_grade            — null String (B31 SCRA dispatch fallback)
    """
    schema_names = exposures.collect_schema().names()
    to_add: list[pl.Expr] = []

    if "guarantor_exposure_class" not in schema_names:
        from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS

        to_add.append(
            pl.col("guarantor_entity_type")
            .fill_null("")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
            .alias("guarantor_exposure_class")
        )
    if "guarantor_country_code" not in schema_names:
        to_add.append(pl.lit(None).cast(pl.String).alias("guarantor_country_code"))
    if "guarantor_is_ccp_client_cleared" not in schema_names:
        to_add.append(pl.lit(None).cast(pl.Boolean).alias("guarantor_is_ccp_client_cleared"))
    if "guarantor_scra_grade" not in schema_names:
        to_add.append(pl.lit(None).cast(pl.Utf8).alias("guarantor_scra_grade"))

    return exposures.with_columns(to_add) if to_add else exposures


def _build_domestic_guarantor_expr(schema_names: list[str]) -> pl.Expr:
    """Build the Art. 114(4)/(7) domestic CGCB-guarantor currency check.

    Evaluates the domestic-currency test against the guarantee currency (the
    currency of the substituted exposure to the sovereign); the Art. 233(3)
    8% FX haircut separately handles any mismatch between the guarantee and
    the underlying exposure. Falls back to the exposure's pre-FX denomination
    when ``guarantee_currency`` is missing (legacy / no-guarantee rows).
    """
    has_country = "guarantor_country_code" in schema_names
    has_exposure_ccy = "currency" in schema_names or "original_currency" in schema_names
    has_guarantee_ccy = "guarantee_currency" in schema_names

    if has_guarantee_ccy and has_exposure_ccy:
        ccy_expr = pl.col("guarantee_currency").fill_null(denomination_currency_expr(schema_names))
    elif has_guarantee_ccy:
        ccy_expr = pl.col("guarantee_currency")
    elif has_exposure_ccy:
        ccy_expr = denomination_currency_expr(schema_names)
    else:
        ccy_expr = None

    if not has_country or ccy_expr is None:
        return pl.lit(False)
    return build_domestic_cgcb_guarantor_expr("guarantor_country_code", ccy_expr)


def _build_guarantor_rw_expr(
    is_domestic_guarantor: pl.Expr,
    is_basel_3_1: bool,
    institution_short_term_flag_col: str | None = None,
) -> pl.Expr:
    """Compile the shared guarantor RW chain with the SA path's bindings.

    Thin wrapper over ``data/tables/guarantor_rw.build_guarantor_rw_expr`` —
    the single rulepack-compiled source for the guarantor branch chain
    (branch order, tables and the unrated PSE/RGLA approximation are
    documented there). The SA path binds its ``guarantor_*`` column names,
    the Art. 114(4)/(7) domestic-CGCB currency test, the Art. 120(2)
    short-term institution scratch flag, and the ``guaranteed_portion``
    no-guarantee guard.
    """
    return build_guarantor_rw_expr(
        exposure_class_col="guarantor_exposure_class",
        entity_type_col="guarantor_entity_type",
        cqs_col="guarantor_cqs",
        country_code_col="guarantor_country_code",
        ccp_client_cleared_col="guarantor_is_ccp_client_cleared",
        scra_grade_col="guarantor_scra_grade",
        is_basel_3_1=is_basel_3_1,
        domestic_cgcb_expr=is_domestic_guarantor,
        short_term_flag_col=institution_short_term_flag_col,
        no_guarantee_expr=pl.col("guaranteed_portion") <= 0,
    )
