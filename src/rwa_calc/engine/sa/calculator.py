"""
Standardised Approach (SA) Calculator for RWA.

Implements CRR Art. 112-134 and Basel 3.1 CRE20 risk weight lookups and RWA
calculation. Supports both frameworks via config.is_basel_3_1 branching.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- CQS-based risk weight lookup (sovereign, institution, corporate)
- LTV-based weights for real estate (CRR split vs Basel 3.1 LTV bands)
- ADC exposure treatment (Basel 3.1: 150% / 100% pre-sold)
- Revised Basel 3.1 corporate CQS weights (CQS3: 75%, CQS5: 100%)
- SCRA-based institution risk weights for unrated exposures (Basel 3.1)
- Investment-grade corporate treatment (65%, Basel 3.1)
- SME corporate treatment (85%, Basel 3.1)
- Subordinated debt flat 150% (Basel 3.1)
- Defaulted exposure treatment (CRR Art. 127 / CRE20.88-90)
- Supporting factor application (CRR only — removed under Basel 3.1)
- RWA calculation (EAD × RW × supporting factor)

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 127: Defaulted exposure risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
- CRE20.16-21: Basel 3.1 institution ECRA/SCRA risk weights
- CRE20.22-26: Basel 3.1 revised corporate CQS risk weights
- CRE20.47-49: Basel 3.1 subordinated debt, investment-grade, SME corporate
- CRE20.88-90: Basel 3.1 defaulted exposure risk weights
- PRA Art. 124F: Basel 3.1 residential RE (general) loan-splitting
- CRE20.82: Basel 3.1 residential RE (income-producing) LTV bands
- CRE20.85: Basel 3.1 commercial RE (general) preferential treatment
- CRE20.86: Basel 3.1 commercial RE (income-producing) LTV bands
- CRE20.87-88: Basel 3.1 ADC exposures
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SAResultBundle
from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    ERROR_EQUITY_IN_MAIN_TABLE,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.tables.b31_risk_weights import (
    B31_CORPORATE_INVESTMENT_GRADE_RW,
    B31_CORPORATE_NON_INVESTMENT_GRADE_RW,
    B31_CORPORATE_SME_RW,
    B31_COVERED_BOND_UNRATED_FROM_SCRA,
    B31_DEFAULTED_PROVISION_THRESHOLD,
    B31_DEFAULTED_RESI_RE_NON_INCOME_RW,
    B31_DEFAULTED_RW_HIGH_PROVISION,
    B31_DEFAULTED_RW_LOW_PROVISION,
    B31_ECRA_SHORT_TERM_RISK_WEIGHTS,
    B31_HIGH_RISK_RW,
    B31_SCRA_RISK_WEIGHTS,
    B31_SCRA_SHORT_TERM_RISK_WEIGHTS,
    B31_SUBORDINATED_DEBT_RW,
    b31_adc_rw_expr,
    b31_commercial_rw_expr,
    b31_other_re_rw_expr,
    b31_residential_rw_expr,
    b31_sa_sl_rw_expr,
    get_b31_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.crr_risk_weights import (
    COMMERCIAL_RE_PARAMS,
    COVERED_BOND_UNRATED_DERIVATION,
    CRR_DEFAULTED_PROVISION_THRESHOLD,
    CRR_DEFAULTED_RW_HIGH_PROVISION,
    CRR_DEFAULTED_RW_LOW_PROVISION,
    HIGH_RISK_RW,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_UNRATED_RW_CRR,
    IO_ZERO_RW,
    MDB_NAMED_ZERO_RW,
    MDB_UNRATED_RW,
    OTHER_ITEMS_CASH_RW,
    OTHER_ITEMS_COLLECTION_RW,
    OTHER_ITEMS_DEFAULT_RW,
    PSE_SHORT_TERM_RW,
    PSE_UNRATED_DEFAULT_RW,
    QCCP_CLIENT_CLEARED_RW,
    QCCP_PROPRIETARY_RW,
    RESIDENTIAL_MORTGAGE_PARAMS,
    RETAIL_RISK_WEIGHT,
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_UK_DEVOLVED_RW,
    RGLA_UNRATED_DEFAULT_RW,
    build_institution_guarantor_rw_expr,
    get_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.domain.enums import CQS, ApproachType, CRMCollateralMethod

# Importing the namespace module registers the ``lf.sa`` fluent API with Polars
# and makes ``SA_INPUT_CONTRACT`` available here without duplicating the schema.
from rwa_calc.engine.sa.namespace import SA_INPUT_CONTRACT as _SA_INPUT_CONTRACT  # noqa: F401

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# FLOAT-CONVERTED RISK WEIGHT CONSTANTS
# Authoritative Decimal values live in data/tables/*.py. Derived once at
# module load for use with pl.lit() in Polars expressions, avoiding repeated
# Decimal->float conversions inside when/then chains.
#
# Grouped into three framework-scoped dicts (shared / CRR / B31) — mirrors the
# dict-comprehension pattern used by engine/equity/calculator.py so the arch
# check (scripts/arch_check.py) does not flag individual ``float(X)`` aliases.
# =============================================================================

# Framework-shared scalars — used under both CRR and Basel 3.1.
_SA_SHARED_RW: dict[str, float] = {
    # QCCP trade exposures (CRR Art. 306, CRE54.14-15)
    "qccp_client_cleared": float(QCCP_CLIENT_CLEARED_RW),
    "qccp_proprietary": float(QCCP_PROPRIETARY_RW),
    # PSE short-term & unrated (Art. 116)
    "pse_short_term": float(PSE_SHORT_TERM_RW),
    "pse_unrated": float(PSE_UNRATED_DEFAULT_RW),
    # RGLA (Art. 115)
    "rgla_uk_devolved": float(RGLA_UK_DEVOLVED_RW),
    "rgla_domestic": float(RGLA_DOMESTIC_CURRENCY_RW),
    "rgla_unrated": float(RGLA_UNRATED_DEFAULT_RW),
    # MDB / International Organisations (Art. 117-118)
    "mdb_named": float(MDB_NAMED_ZERO_RW),
    "mdb_unrated": float(MDB_UNRATED_RW),
    "io": float(IO_ZERO_RW),
    # Other Items (Art. 134)
    "other_cash": float(OTHER_ITEMS_CASH_RW),
    "other_collection": float(OTHER_ITEMS_COLLECTION_RW),
    "other_default": float(OTHER_ITEMS_DEFAULT_RW),
    # Regulatory retail — 75% flat (Art. 123 / CRE20.65)
    "retail": float(RETAIL_RISK_WEIGHT),
}

# CRR-specific scalars (Art. 112-134).
_SA_CRR_RW: dict[str, float] = {
    "high_risk": float(HIGH_RISK_RW),
    # Residential mortgage loan-splitting (Art. 125)
    "resi_ltv_threshold": float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"]),
    "resi_rw_low": float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"]),
    "resi_rw_high": float(RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"]),
    # Commercial RE (Art. 126)
    "cre_ltv_threshold": float(COMMERCIAL_RE_PARAMS["ltv_threshold"]),
    "cre_rw_low": float(COMMERCIAL_RE_PARAMS["rw_low_ltv"]),
    "cre_rw_standard": float(COMMERCIAL_RE_PARAMS["rw_standard"]),
    # Institution short-term (Art. 121, original maturity <=3m)
    "inst_st_low": float(INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR[CQS.CQS1]),
    "inst_st_mid": float(INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR[CQS.CQS4]),
    "inst_st_high": float(INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR[CQS.CQS6]),
    "inst_unrated_st": float(INSTITUTION_SHORT_TERM_UNRATED_RW_CRR),
    # Defaulted exposure treatment (Art. 127)
    "defaulted_threshold": float(CRR_DEFAULTED_PROVISION_THRESHOLD),
    "defaulted_high": float(CRR_DEFAULTED_RW_HIGH_PROVISION),
    "defaulted_low": float(CRR_DEFAULTED_RW_LOW_PROVISION),
}

# Basel 3.1 specific scalars (PRA PS1/26, CRE20).
_SA_B31_RW: dict[str, float] = {
    "high_risk": float(B31_HIGH_RISK_RW),
    # ECRA short-term institution weights (Table 4) — CQS 1-5 vs CQS 6
    "ecra_st_low": float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[1]),
    "ecra_st_high": float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[6]),
    # SCRA unrated institution weights (CRE20.16-21) — long-term
    "scra_a": float(B31_SCRA_RISK_WEIGHTS["A"]),
    "scra_ae": float(B31_SCRA_RISK_WEIGHTS["A_ENHANCED"]),
    "scra_b": float(B31_SCRA_RISK_WEIGHTS["B"]),
    "scra_c": float(B31_SCRA_RISK_WEIGHTS["C"]),
    # SCRA unrated institution weights — short-term (<=3m)
    "scra_st_a": float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"]),
    "scra_st_b": float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["B"]),
    "scra_st_c": float(B31_SCRA_SHORT_TERM_RISK_WEIGHTS["C"]),
    # Corporate CQS-mapped weights (CRE20.22-26, 47-49)
    "corporate_ig": float(B31_CORPORATE_INVESTMENT_GRADE_RW),
    "corporate_nig": float(B31_CORPORATE_NON_INVESTMENT_GRADE_RW),
    "corporate_sme": float(B31_CORPORATE_SME_RW),
    "sub_debt": float(B31_SUBORDINATED_DEBT_RW),
    # Defaulted exposure treatment (CRE20.88-90)
    "defaulted_threshold": float(B31_DEFAULTED_PROVISION_THRESHOLD),
    "defaulted_high": float(B31_DEFAULTED_RW_HIGH_PROVISION),
    "defaulted_low": float(B31_DEFAULTED_RW_LOW_PROVISION),
    "defaulted_resi_re_non_income": float(B31_DEFAULTED_RESI_RE_NON_INCOME_RW),
}


def _crr_unrated_cb_rw_expr() -> pl.Expr:
    """Build Polars expression for CRR Art. 129(5) unrated covered bond RW derivation.

    Derives covered bond RW from the issuing institution's CQS via two-step lookup:
      1. Institution CQS → institution RW (Art. 120 Table 3)
      2. Institution RW → covered bond RW (Art. 129(5) derivation table)

    When ``cp_institution_cqs`` is null (institution itself is unrated), uses
    Art. 121 fallback institution RW (100%) → CB 50%.

    References:
        CRR Art. 120 Table 3: Institution risk weights (CQS 2 = 50%)
        CRR Art. 129(5): Unrated covered bond derivation from institution RW
    """
    inst_table = INSTITUTION_RISK_WEIGHTS_CRR

    # Pre-compute CQS → CB RW by chaining institution RW through the derivation table
    cqs_to_cb_rw: dict[int, float] = {}
    for cqs_val in [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
        inst_rw = inst_table[cqs_val]
        cb_rw = COVERED_BOND_UNRATED_DERIVATION[inst_rw]
        cqs_to_cb_rw[int(cqs_val)] = float(cb_rw)

    # Unrated institution: sovereign-derived
    unrated_inst_rw = inst_table[CQS.UNRATED]
    unrated_cb_rw = float(COVERED_BOND_UNRATED_DERIVATION[unrated_inst_rw])

    # Build when/then chain from cp_institution_cqs
    expr = pl.when(pl.col("cp_institution_cqs") == 1).then(pl.lit(cqs_to_cb_rw[1]))
    for cqs_int in [2, 3, 4, 5, 6]:
        expr = expr.when(pl.col("cp_institution_cqs") == cqs_int).then(
            pl.lit(cqs_to_cb_rw[cqs_int])
        )
    # Fallback: cp_institution_cqs is null (unrated institution) or unexpected value
    return expr.otherwise(pl.lit(unrated_cb_rw))


def _b31_unrated_cb_rw_expr() -> pl.Expr:
    """Build Polars expression for B31 Art. 129(5) unrated covered bond RW derivation.

    Derives covered bond RW from the issuing institution's senior unsecured RW,
    which can come from either source:
      1. ECRA (rated institution): cp_institution_cqs → institution RW → CB RW
      2. SCRA (unrated institution): cp_scra_grade → CB RW

    Art. 129(5) operates on the resulting institution RW regardless of source
    (ECRA or SCRA). The ECRA path is checked first; if cp_institution_cqs is
    null, falls back to the SCRA path.

    References:
        PRA PS1/26 Art. 120 Table 3 ECRA: Institution risk weights (CQS 2 = 30%)
        PRA PS1/26 Art. 120A: SCRA institution risk weights
        PRA PS1/26 Art. 129(5): Unrated covered bond derivation from institution RW
    """
    inst_table = INSTITUTION_RISK_WEIGHTS_B31_ECRA
    cqs_to_cb_rw: dict[int, float] = {}
    for cqs_val in [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
        inst_rw = inst_table[cqs_val]
        cb_rw = COVERED_BOND_UNRATED_DERIVATION[inst_rw]
        cqs_to_cb_rw[int(cqs_val)] = float(cb_rw)

    # Build when/then: ECRA first (cp_institution_cqs)
    expr = pl.when(pl.col("cp_institution_cqs") == 1).then(pl.lit(cqs_to_cb_rw[1]))
    for cqs_int in [2, 3, 4, 5, 6]:
        expr = expr.when(pl.col("cp_institution_cqs") == cqs_int).then(
            pl.lit(cqs_to_cb_rw[cqs_int])
        )
    # SCRA fallback (cp_scra_grade) for unrated issuers
    for grade, cb_rw in B31_COVERED_BOND_UNRATED_FROM_SCRA.items():
        expr = expr.when(pl.col("cp_scra_grade") == grade).then(pl.lit(float(cb_rw)))
    # Conservative default: Grade C equivalent (100%)
    return expr.otherwise(pl.lit(1.00))


# ---------------------------------------------------------------------------
# Chain-appender helpers for the risk-weight when/then expression.
#
# Each function takes an in-progress ``pl.when(...)..then(...)`` chain and
# appends a themed group of branches (real estate, institutions, etc.),
# returning the extended chain. ORDER of branches within a chain matters —
# the first matching ``.when()`` wins — so the framework override methods
# call these in the sequence prescribed by the regulation.
# ---------------------------------------------------------------------------


def _b31_append_real_estate_branches(chain: pl.Expr, uc: pl.Expr) -> pl.Expr:
    """Append Basel 3.1 real-estate branches (ADC / other-RE / resi / CRE)."""
    is_re_class = (
        uc.str.contains("MORTGAGE", literal=True)
        | uc.str.contains("RESIDENTIAL", literal=True)
        | uc.str.contains("COMMERCIAL", literal=True)
        | uc.str.contains("CRE", literal=True)
        | (pl.col("property_type").fill_null("").is_in(["residential", "commercial"]))
    )
    is_non_qualifying = pl.col("is_qualifying_re").fill_null(True) == False  # noqa: E712
    return (
        # ADC: 150% or 100% pre-sold (CRE20.87-88)
        chain.when(pl.col("is_adc").fill_null(False))
        .then(b31_adc_rw_expr())
        # Other RE (Art. 124J): non-qualifying RE that fails Art. 124A criteria.
        # Routes before qualifying RE branches so non-qualifying exposures get
        # 150% (income) / cp RW (resi) / max(60%,cp) (cre). Null is_qualifying_re
        # defaults to qualifying — backward compatible with existing data.
        .when(is_non_qualifying & is_re_class)
        .then(b31_other_re_rw_expr("_cqs_risk_weight"))
        # Residential mortgage: loan-split (Art. 124F) / LTV-band (Art. 124G)
        .when(
            uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True)
        )
        .then(b31_residential_rw_expr("_cqs_risk_weight"))
        # Commercial RE: LTV-band or min() (CRE20.85/86)
        .when(
            uc.str.contains("COMMERCIAL", literal=True)
            | uc.str.contains("CRE", literal=True)
            | (pl.col("property_type").fill_null("") == "commercial")
        )
        .then(b31_commercial_rw_expr("_cqs_risk_weight"))
    )


def _b31_append_institution_maturity_branches(chain: pl.Expr, uc: pl.Expr) -> pl.Expr:
    """Append Basel 3.1 ECRA / SCRA institution maturity branches."""
    is_institution = uc.str.contains("INSTITUTION", literal=True)
    is_rated = pl.col("cqs").is_not_null() & (pl.col("cqs") > 0)
    is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
    original_mty = pl.col("original_maturity_years").fill_null(1.0)
    return (
        # ECRA short-term rated institutions (Table 4, Art. 120(2)).
        # Keys on ORIGINAL maturity <= 3m -> CQS 1-5 = 20%, CQS 6 = 150%.
        # Art. 120(2A) extends Table 4 to ORIGINAL maturity <= 6m for exposures
        # arising from the movement of goods.
        chain.when(
            is_institution
            & is_rated
            & (
                (original_mty <= 0.25)
                | (pl.col("is_short_term_trade_lc").fill_null(False) & (original_mty <= 0.5))
            )
        )
        .then(
            pl.when(pl.col("cqs") <= 5)
            .then(pl.lit(_SA_B31_RW["ecra_st_low"]))
            .otherwise(pl.lit(_SA_B31_RW["ecra_st_high"]))
        )
        # SCRA short-term unrated institutions (Art. 121(3)):
        # ORIGINAL maturity <= 3m -> Grade A/A_ENHANCED = 20%, B = 50%, C = 150%.
        # Null SCRA grade defaults to Grade C (conservative treatment per
        # PRA PS1/26 Art. 120A).
        .when(is_institution & is_unrated & (original_mty <= 0.25))
        .then(
            pl.when(pl.col("cp_scra_grade").is_in(["A", "A_ENHANCED"]))
            .then(pl.lit(_SA_B31_RW["scra_st_a"]))
            .when(pl.col("cp_scra_grade") == "B")
            .then(pl.lit(_SA_B31_RW["scra_st_b"]))
            .otherwise(pl.lit(_SA_B31_RW["scra_st_c"]))
        )
        # SCRA long-term unrated institutions (>3m) (CRE20.16-21)
        .when(is_institution & is_unrated)
        .then(
            pl.when(pl.col("cp_scra_grade") == "A_ENHANCED")
            .then(pl.lit(_SA_B31_RW["scra_ae"]))
            .when(pl.col("cp_scra_grade") == "A")
            .then(pl.lit(_SA_B31_RW["scra_a"]))
            .when(pl.col("cp_scra_grade") == "B")
            .then(pl.lit(_SA_B31_RW["scra_b"]))
            .otherwise(pl.lit(_SA_B31_RW["scra_c"]))
        )
    )


def _crr_append_real_estate_branches(chain: pl.Expr, uc: pl.Expr) -> pl.Expr:
    """Append CRR residential LTV-split and commercial RE branches (Art. 125-126)."""
    ltv_safe = pl.col("ltv").fill_null(1.0)
    return (
        # Residential mortgage: LTV split (CRR Art. 125)
        chain.when(
            uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True)
        )
        .then(
            pl.when(pl.col("ltv").fill_null(0.0) <= _SA_CRR_RW["resi_ltv_threshold"])
            .then(pl.lit(_SA_CRR_RW["resi_rw_low"]))
            .otherwise(
                _SA_CRR_RW["resi_rw_low"] * _SA_CRR_RW["resi_ltv_threshold"] / ltv_safe
                + _SA_CRR_RW["resi_rw_high"]
                * (ltv_safe - _SA_CRR_RW["resi_ltv_threshold"])
                / ltv_safe
            )
        )
        # Commercial RE: LTV + income cover (CRR Art. 126)
        .when(
            uc.str.contains("COMMERCIAL", literal=True)
            | uc.str.contains("CRE", literal=True)
            | (pl.col("property_type").fill_null("") == "commercial")
        )
        .then(
            pl.when(
                (ltv_safe <= _SA_CRR_RW["cre_ltv_threshold"])
                & pl.col("has_income_cover").fill_null(False)
            )
            .then(pl.lit(_SA_CRR_RW["cre_rw_low"]))
            .otherwise(pl.lit(_SA_CRR_RW["cre_rw_standard"]))
        )
    )


def _crr_append_institution_maturity_branches(chain: pl.Expr, uc: pl.Expr) -> pl.Expr:
    """Append CRR Art. 120/121 short-term institution branches."""
    is_institution = uc.str.contains("INSTITUTION", literal=True)
    is_rated = pl.col("cqs").is_not_null() & (pl.col("cqs") > 0)
    is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
    residual_mty = pl.col("residual_maturity_years").fill_null(1.0)
    original_mty = pl.col("original_maturity_years").fill_null(1.0)
    return (
        # Art. 120(2) Table 4: rated institution short-term (residual maturity <= 3m).
        chain.when(is_institution & is_rated & (residual_mty <= 0.25))
        .then(
            pl.when(pl.col("cqs") <= 3)
            .then(pl.lit(_SA_CRR_RW["inst_st_low"]))
            .when(pl.col("cqs") <= 5)
            .then(pl.lit(_SA_CRR_RW["inst_st_mid"]))
            .otherwise(pl.lit(_SA_CRR_RW["inst_st_high"]))
        )
        # Art. 121(3): unrated institution with ORIGINAL effective maturity <= 3m.
        # Overrides the Table 5 sovereign-derived fallback; Art. 121(6) sovereign
        # floor (applied later) still raises this in FX.
        .when(is_institution & is_unrated & (original_mty <= 0.25))
        .then(pl.lit(_SA_CRR_RW["inst_unrated_st"]))
    )


# ---------------------------------------------------------------------------
# Guarantee-substitution helpers (CRR Art. 213-217)
#
# The SA calculator's guarantee-substitution stage relies on a few columns
# that may be missing when the calculator is invoked directly from tests
# (i.e. bypassing the CRM processor). These helpers own the defensive
# preparation and the guarantor-RW when/then chain in one place.
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
    """
    schema_names = exposures.collect_schema().names()
    to_add: list[pl.Expr] = []

    if "guarantor_exposure_class" not in schema_names:
        from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

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

    return exposures.with_columns(to_add) if to_add else exposures


def _build_domestic_guarantor_expr(schema_names: list[str]) -> pl.Expr:
    """Build the Art. 114(3)/(4) domestic CGCB-guarantor currency check.

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


def _build_guarantor_rw_expr(is_domestic_guarantor: pl.Expr, is_basel_3_1: bool) -> pl.Expr:
    """Build the full when/then chain that maps a guarantor to its RW.

    Uses ``guarantor_exposure_class`` (derived from ENTITY_TYPE_TO_SA_CLASS by
    the CRM processor) rather than regex on entity_type, ensuring all valid
    entity types are covered.

    Branch order (first match wins):
        no guarantee -> null
        domestic CGCB sovereign (Art. 114(3)/(4)) -> 0%
        CGCB CQS table
        CCP (CRR Art. 306, CRE54.14-15)
        Named MDB (Art. 117(2)) / International Organisation (Art. 118)
        MDB Table 2B (Art. 117(1))
        Institution (ECRA / SCRA via build_institution_guarantor_rw_expr)
        PSE (Art. 116(2) Table 2A, sovereign-derived for unrated)
        RGLA (Art. 115(1)(b) Table 1B, sovereign-derived for unrated)
        Corporate (Art. 122 corporate CQS table)
        else -> null (no substitution)
    """
    gec = pl.col("guarantor_exposure_class").fill_null("")
    cqs = pl.col("guarantor_cqs")
    guarantor_country_is_gb = pl.col("guarantor_country_code").fill_null("") == "GB"
    sovereign_derived_unrated = (
        pl.when(guarantor_country_is_gb).then(pl.lit(0.20)).otherwise(pl.lit(1.0))
    )

    return (
        pl.when(pl.col("guaranteed_portion") <= 0)
        .then(pl.lit(None).cast(pl.Float64))
        # Art. 114(3)/(4): Domestic sovereign -> 0% regardless of CQS.
        .when((gec == "central_govt_central_bank") & is_domestic_guarantor)
        .then(pl.lit(0.0))
        # CGCB guarantors via CQS (Table 1 — sovereign weights).
        .when(gec == "central_govt_central_bank")
        .then(
            pl.when(cqs == 1)
            .then(pl.lit(0.0))
            .when(cqs == 2)
            .then(pl.lit(0.20))
            .when(cqs == 3)
            .then(pl.lit(0.50))
            .when(cqs.is_in([4, 5]))
            .then(pl.lit(1.0))
            .when(cqs == 6)
            .then(pl.lit(1.50))
            .otherwise(pl.lit(1.0))  # Unrated
        )
        # CCP guarantors: 2% proprietary / 4% client-cleared
        # (CRR Art. 306, CRE54.14-15) — overrides institution CQS weights.
        .when(pl.col("guarantor_entity_type") == "ccp")
        .then(
            pl.when(pl.col("guarantor_is_ccp_client_cleared").fill_null(False))
            .then(pl.lit(_SA_SHARED_RW["qccp_client_cleared"]))
            .otherwise(pl.lit(_SA_SHARED_RW["qccp_proprietary"]))
        )
        # Named MDB (Art. 117(2)): 0% unconditional.
        .when((gec == "mdb") & (pl.col("guarantor_entity_type").fill_null("") == "mdb_named"))
        .then(pl.lit(0.0))
        # International Organisation (Art. 118): 0% unconditional.
        .when(
            (gec == "mdb") & (pl.col("guarantor_entity_type").fill_null("") == "international_org")
        )
        .then(pl.lit(0.0))
        # Rated / unrated non-named MDB — Table 2B (Art. 117(1)).
        .when(gec == "mdb")
        .then(
            pl.when(cqs == 1)
            .then(pl.lit(0.20))
            .when(cqs == 2)
            .then(pl.lit(0.30))
            .when(cqs == 3)
            .then(pl.lit(0.50))
            .when(cqs.is_in([4, 5]))
            .then(pl.lit(1.0))
            .when(cqs == 6)
            .then(pl.lit(1.50))
            .otherwise(pl.lit(0.50))  # Unrated MDB = 50% (Table 2B)
        )
        # Institution guarantors — RW driven from INSTITUTION_RISK_WEIGHTS_CRR /
        # INSTITUTION_RISK_WEIGHTS_B31_ECRA so the dicts remain the single source
        # of truth.
        .when(gec == "institution")
        .then(build_institution_guarantor_rw_expr("guarantor_cqs", is_basel_3_1))
        # PSE guarantors — Art. 116(2) Table 2A for rated, sovereign-derived for unrated.
        .when(gec == "pse")
        .then(
            pl.when(cqs == 1)
            .then(pl.lit(0.20))
            .when(cqs == 2)
            .then(pl.lit(0.50))
            .when(cqs == 3)
            .then(pl.lit(0.50))
            .when(cqs.is_in([4, 5]))
            .then(pl.lit(1.0))
            .when(cqs == 6)
            .then(pl.lit(1.50))
            .otherwise(sovereign_derived_unrated)
        )
        # RGLA guarantors — Art. 115(1)(b) Table 1B for rated, sovereign-derived for unrated.
        .when(gec == "rgla")
        .then(
            pl.when(cqs == 1)
            .then(pl.lit(0.20))
            .when(cqs == 2)
            .then(pl.lit(0.50))
            .when(cqs == 3)
            .then(pl.lit(0.50))
            .when(cqs.is_in([4, 5]))
            .then(pl.lit(1.0))
            .when(cqs == 6)
            .then(pl.lit(1.50))
            .otherwise(sovereign_derived_unrated)
        )
        # Corporate guarantors — Art. 122 corporate CQS table.
        .when(gec.is_in(["corporate", "corporate_sme"]))
        .then(
            pl.when(cqs == 1)
            .then(pl.lit(0.20))
            .when(cqs == 2)
            .then(pl.lit(0.50))
            .when(cqs.is_in([3, 4]))
            .then(pl.lit(1.0))
            .when(cqs.is_in([5, 6]))
            .then(pl.lit(1.50))
            .otherwise(pl.lit(1.0))
        )
        .otherwise(pl.lit(None).cast(pl.Float64))
    )


@dataclass
class SACalculationError:
    """Error during SA calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class SACalculator:
    """
    Calculate RWA using Standardised Approach.

    Implements SACalculatorProtocol for:
    - CQS-based risk weight lookup (sovereign, institution, corporate)
    - Fixed retail risk weight (75%)
    - LTV-based real estate risk weights
    - Supporting factor application (CRR only)

    Usage:
        calculator = SACalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using Standardised Approach.

        Args:
            data: CRM-adjusted exposures (uses sa_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with SA RWA calculations
        """
        bundle = self.get_sa_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors, preserving any
        # CalculationError objects already created by sub-components
        calc_errors: list[CalculationError] = []
        for err in bundle.errors:
            if isinstance(err, CalculationError):
                calc_errors.append(err)
            else:
                calc_errors.append(
                    CalculationError(
                        code="SA001",
                        message=str(err),
                        severity=ErrorSeverity.ERROR,
                        category=ErrorCategory.CALCULATION,
                    )
                )

        return LazyFrameResult(
            frame=bundle.results,
            errors=calc_errors,
        )

    def get_sa_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            SAResultBundle with results and audit trail
        """
        errors: list[CalculationError] = []

        # Get SA exposures
        exposures = data.sa_exposures

        # Warn if equity-class rows are present in the main exposure table.
        # These get correct SA equity RW (250% B31, 100% CRR) but miss
        # full equity treatment (CIU approaches, transitional floor, IRB Simple).
        self._warn_equity_in_main_table(exposures, errors)

        # Step 1: Look up risk weights
        exposures = self._apply_risk_weights(exposures, config)

        # Step 1b: Apply FCSM risk weight substitution (Art. 222 Simple Method)
        exposures = self._apply_fcsm_rw_substitution(exposures, config)

        # Step 1c: Apply life insurance risk weight mapping (Art. 232)
        exposures = self._apply_life_insurance_rw_mapping(exposures)

        # Step 2: Apply guarantee substitution (blended risk weight)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 2b: Apply currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 2c: Apply due diligence override (Basel 3.1 Art. 110A)
        dd_errors: list[CalculationError] = []
        exposures = self._apply_due_diligence_override(exposures, config, errors=dd_errors)
        errors.extend(dd_errors)

        # Step 3: Calculate pre-factor RWA
        exposures = exposures.sa.calculate_rwa()

        # Step 4: Apply supporting factors (CRR only)
        sf_errors: list[CalculationError] = []
        exposures = exposures.sa.apply_supporting_factors(config, errors=sf_errors)
        errors.extend(sf_errors)

        # Step 5: Build audit trail
        audit = exposures.sa.build_audit()

        return SAResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=errors,
        )

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights to SA rows on a unified frame.

        Operates on the full unified frame (SA + IRB + slotting rows together).
        Only modifies columns for rows where approach == 'standardised'.

        Steps:
        1. Join risk weight table (unconditional — SA-equivalent RW for output floor)
        2. Apply SA-specific RW overrides (mortgage LTV, retail fixed, etc.)
        3. Apply SA guarantee substitution
        4. Calculate RWA = EAD x RW (SA rows only)
        5. Apply supporting factors (SA rows only)

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with SA columns populated for SA rows
        """
        is_sa = pl.col("approach") == ApproachType.SA.value

        # Step 1-2: Apply risk weights (runs unconditionally — also provides
        # SA-equivalent RW for IRB output floor)
        exposures = self._apply_risk_weights(exposures, config)

        # Step 2b: FCSM risk weight substitution (Art. 222 Simple Method)
        exposures = self._apply_fcsm_rw_substitution(exposures, config)

        # Step 2c: Life insurance risk weight mapping (Art. 232)
        exposures = self._apply_life_insurance_rw_mapping(exposures)

        # Step 3: Guarantee substitution (already conditional on guaranteed_portion > 0)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 3a: Currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 3a2: Due diligence override (Basel 3.1 Art. 110A)
        exposures = self._apply_due_diligence_override(exposures, config)

        # Step 3b: Store SA-equivalent RWA for ALL rows before IRB calculator
        # overwrites risk_weight. The output floor needs: floor_rwa = floor_pct × sa_rwa.
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        if config.output_floor.enabled:
            exposures = exposures.with_columns(
                (pl.col(ead_col) * pl.col("risk_weight")).alias("sa_rwa"),
            )

        # Step 4: Calculate pre-factor RWA (SA rows only)
        exposures = exposures.with_columns(
            [
                pl.when(is_sa)
                .then(pl.col(ead_col) * pl.col("risk_weight"))
                .otherwise(
                    pl.col("rwa_pre_factor")
                    if "rwa_pre_factor" in schema.names()
                    else pl.lit(None).cast(pl.Float64)
                )
                .alias("rwa_pre_factor"),
            ]
        )

        # Step 5: Apply supporting factors (SA rows only)
        exposures = exposures.sa.apply_supporting_factors(config)

        return exposures

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Unlike calculate_unified(), expects only SA rows — no approach guards
        needed for RWA calculation. Risk weight join runs on ~55K SA rows
        instead of the full 100K unified frame.

        Args:
            exposures: Pre-filtered SA rows only
            config: Calculation configuration

        Returns:
            LazyFrame with SA RWA columns populated
        """
        # Step 1-2: Apply risk weights
        exposures = self._apply_risk_weights(exposures, config)

        # Step 2b: FCSM risk weight substitution (Art. 222 Simple Method)
        exposures = self._apply_fcsm_rw_substitution(exposures, config)

        # Step 2c: Life insurance risk weight mapping (Art. 232)
        exposures = self._apply_life_insurance_rw_mapping(exposures)

        # Step 3: Guarantee substitution
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 3b: Currency mismatch multiplier (Basel 3.1 Art. 123B)
        exposures = self._apply_currency_mismatch_multiplier(exposures, config)

        # Step 3c: Due diligence override (Basel 3.1 Art. 110A)
        exposures = self._apply_due_diligence_override(exposures, config)

        # Step 4: Calculate pre-factor RWA (all rows are SA — no guard needed)
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        exposures = exposures.with_columns(
            (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
        )

        # Step 5: Apply supporting factors
        exposures = exposures.sa.apply_supporting_factors(config)

        # Step 6: Standardize output for aggregator
        schema = exposures.collect_schema()
        approach_expr = (
            pl.col("approach") if "approach" in schema.names() else pl.lit(ApproachType.SA.value)
        )
        exposures = exposures.with_columns(
            approach_expr.alias("approach_applied"),
            pl.col("rwa_post_factor").alias("rwa_final"),
        )

        return exposures

    def _apply_risk_weights(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Look up and apply risk weights based on exposure class.

        Orchestrates the three-phase SA risk weight assignment:
            1. Setup — ensure columns, derive maturity, classify, join CQS table
            2. Framework-specific when/then overrides (CRR vs Basel 3.1)
            3. Cleanup — sovereign floor, defaulted RW blending, drop temp cols

        Args:
            exposures: SA exposures with classification
            config: Calculation configuration

        Returns:
            Exposures with risk_weight column added
        """
        exposures, uc, is_domestic_currency = self._prepare_risk_weight_lookup(exposures, config)

        if config.is_basel_3_1:
            exposures = self._apply_b31_risk_weight_overrides(
                exposures, uc, is_domestic_currency, config
            )
        else:
            exposures = self._apply_crr_risk_weight_overrides(exposures, uc, is_domestic_currency)

        # Art. 121(6) (CRR) / CRE20.22 (Basel 3.1): Sovereign RW floor for
        # FX-denominated unrated institution exposures. Exception:
        # self-liquidating trade items with original maturity <= 1yr.
        exposures = self._apply_sovereign_floor_for_institutions(exposures, is_domestic_currency)

        # Art. 127 defaulted risk weight (secured/unsecured split). Runs after
        # the base RW when-chain so defaulted exposures have their non-defaulted
        # base RW available for blending with collateral coverage.
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        exposures = self._apply_defaulted_risk_weight(exposures, config, ead_col)

        # Drop temporary columns used only during risk-weight application.
        schema_names = exposures.collect_schema().names()
        temp_cols = [
            "_lookup_class",
            "_lookup_cqs",
            "_upper_class",
            "_cqs_risk_weight",
            "_sovereign_rw",
            "risk_weight_rw",
        ]
        return exposures.drop([c for c in temp_cols if c in schema_names])

    def _prepare_risk_weight_lookup(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> tuple[pl.LazyFrame, pl.Expr, pl.Expr]:
        """Ensure required columns, classify for join, and attach CQS risk weights.

        Returns the exposures frame (with ``_lookup_class`` / ``_lookup_cqs`` /
        ``_upper_class`` / ``risk_weight`` columns added), the uppercase class
        expression reused by override chains, and the domestic-currency flag
        used for CGCB zero-weight treatment and sovereign-derived fallbacks.
        """
        # CQS-based risk weight table — Basel 3.1 uses revised corporate weights
        if config.is_basel_3_1:
            rw_table = get_b31_combined_cqs_risk_weights().lazy()
        else:
            rw_table = get_combined_cqs_risk_weights().lazy()

        # Fill missing optional columns (counterparty attrs, CRM outputs,
        # classifier flags, defensive input-schema fallbacks) from the
        # declarative contract. See SA_INPUT_CONTRACT in namespace.py.
        exposures = ensure_columns(exposures, _SA_INPUT_CONTRACT)

        # Derive original_maturity_years from (maturity_date - value_date) when
        # not supplied directly. Required by Art. 116(3) PSE short-term,
        # Art. 120(2)/(2A) B31 rated institution short-term, Art. 121(3) unrated
        # institution short-term, and Art. 121(6) trade-goods sovereign floor
        # exception — all of which key off "original" maturity, not residual.
        derived_original = (
            pl.col("maturity_date").cast(pl.Int32) - pl.col("value_date").cast(pl.Int32)
        ).cast(pl.Float64) / 365.0
        exposures = exposures.with_columns(
            pl.when(pl.col("original_maturity_years").is_null())
            .then(derived_original)
            .otherwise(pl.col("original_maturity_years"))
            .alias("original_maturity_years")
        )
        schema = exposures.collect_schema()

        # CRR Art. 114(3)/(4): Domestic CGCB exposures -> 0% RW. Must compare
        # against the exposure's ORIGINAL denomination — the FX converter
        # overwrites `currency` with the reporting currency, so using it
        # directly would reject legitimate Art. 114(4) 0% treatment for any
        # non-base-currency exposure.
        ccy_expr = denomination_currency_expr(schema.names())
        is_uk_domestic = (pl.col("cp_country_code") == "GB") & (ccy_expr == "GBP")
        is_eu_domestic = build_eu_domestic_currency_expr("cp_country_code", ccy_expr)
        is_domestic_currency = is_uk_domestic | is_eu_domestic

        # Cache uppercase-class once and map detailed classes onto CQS-lookup
        # classes. Sentinel -1 for null CQS so the left join matches.
        upper = pl.col("exposure_class").str.to_uppercase()
        exposures = exposures.with_columns(
            [
                pl.when(upper.str.contains("CENTRAL_GOVT", literal=True))
                .then(pl.lit("CENTRAL_GOVT_CENTRAL_BANK"))
                .when(upper == "RGLA")
                .then(pl.lit("RGLA"))
                .when(upper == "PSE")
                .then(pl.lit("PSE"))
                .when(upper == "MDB")
                .then(pl.lit("MDB"))
                .when(upper.str.contains("INSTITUTION", literal=True))
                .then(pl.lit("INSTITUTION"))
                .when(upper.str.contains("CORPORATE", literal=True))
                .then(pl.lit("CORPORATE"))
                # Rated SL uses corporate CQS table (Art. 122A(3))
                .when(upper.str.contains("SPECIALISED", literal=True))
                .then(pl.lit("CORPORATE"))
                .when(upper.str.contains("COVERED_BOND", literal=True))
                .then(pl.lit("COVERED_BOND"))
                .otherwise(upper)
                .alias("_lookup_class"),
                pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("_lookup_cqs"),
                upper.alias("_upper_class"),
            ]
        )

        rw_table = rw_table.with_columns(
            pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
        )
        exposures = exposures.join(
            rw_table.select(["exposure_class", "cqs", "risk_weight"]),
            left_on=["_lookup_class", "_lookup_cqs"],
            right_on=["exposure_class", "cqs"],
            how="left",
            suffix="_rw",
        )

        return exposures, pl.col("_upper_class"), is_domestic_currency

    def _apply_b31_risk_weight_overrides(
        self,
        exposures: pl.LazyFrame,
        uc: pl.Expr,
        is_domestic_currency: pl.Expr,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Apply Basel 3.1 class-specific risk-weight overrides (CRE20, PRA PS1/26)."""
        # Save the CQS-based risk weight before overrides — needed for the
        # Basel 3.1 general CRE min(60%, counterparty_rw) logic (CRE20.85).
        exposures = exposures.with_columns(
            pl.col("risk_weight").fill_null(1.0).alias("_cqs_risk_weight")
        )

        # Build the override chain in regulatory precedence order:
        #   CGCB / QCCP / subordinated debt   [early overrides, before RE/CQS]
        #   real estate                        (ADC, other-RE, residential, commercial)
        #   sovereign-like                     (PSE, RGLA)
        #   MDB / IO
        #   institution maturity               (ECRA short, SCRA short, SCRA long)
        #   corporate / retail / misc          (IG, SME, SL, QRRE, payroll, retail, ...)
        #   covered bond / high risk / other items / equity
        chain = (
            pl.when(uc.str.contains("CENTRAL_GOVT", literal=True) & is_domestic_currency)
            .then(pl.lit(0.0))
            # QCCP trade exposures (CRR Art. 306, CRE54.14-15)
            .when(pl.col("cp_entity_type") == "ccp")
            .then(
                pl.when(pl.col("cp_is_ccp_client_cleared").fill_null(False))
                .then(pl.lit(_SA_SHARED_RW["qccp_client_cleared"]))
                .otherwise(pl.lit(_SA_SHARED_RW["qccp_proprietary"]))
            )
            # Subordinated debt: flat 150% (CRE20.47) — overrides all CQS-based
            # weights for institution + corporate.
            .when(
                (pl.col("seniority").fill_null("senior") == "subordinated")
                & (
                    uc.str.contains("INSTITUTION", literal=True)
                    | uc.str.contains("CORPORATE", literal=True)
                )
            )
            .then(pl.lit(_SA_B31_RW["sub_debt"]))
        )

        chain = _b31_append_real_estate_branches(chain, uc)

        # Sovereign-like treatments (PSE then RGLA).
        chain = (
            # PSE short-term (Art. 116(3)): original maturity <= 3m -> 20% flat.
            # Art. 116(3) keys on ORIGINAL maturity — a seasoned long-dated PSE
            # bond with short residual does not qualify.
            chain.when(
                (uc == "PSE")
                & pl.col("original_maturity_years").is_not_null()
                & (pl.col("original_maturity_years") <= 0.25)
            )
            .then(pl.lit(_SA_SHARED_RW["pse_short_term"]))
            # PSE unrated: sovereign-derived (Art. 116(1), Table 2). UK
            # sovereign CQS=1 -> 20%; non-UK falls back to conservative 100%.
            .when((uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(
                pl.when(pl.col("cp_country_code") == "GB")
                .then(pl.lit(0.20))
                .otherwise(pl.lit(_SA_SHARED_RW["pse_unrated"]))
            )
            # RGLA UK devolved govt -> 0% (PRA designation).
            .when(
                (uc == "RGLA")
                & (pl.col("cp_entity_type").fill_null("") == "rgla_sovereign")
                & (pl.col("cp_country_code") == "GB")
            )
            .then(pl.lit(_SA_SHARED_RW["rgla_uk_devolved"]))
            # RGLA domestic currency -> 20% (Art. 115(5)).
            .when((uc == "RGLA") & is_domestic_currency)
            .then(pl.lit(_SA_SHARED_RW["rgla_domestic"]))
            # RGLA unrated non-domestic: sovereign-derived (Table 1A).
            .when((uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(
                pl.when(pl.col("cp_country_code") == "GB")
                .then(pl.lit(0.20))
                .otherwise(pl.lit(_SA_SHARED_RW["rgla_unrated"]))
            )
            # Named MDB -> 0% (Art. 117(2)).
            .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
            .then(pl.lit(_SA_SHARED_RW["mdb_named"]))
            # International Organisation -> 0% (Art. 118).
            .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "international_org"))
            .then(pl.lit(_SA_SHARED_RW["io"]))
            # Unrated non-named MDB -> 50% (Art. 117(1), Table 2B).
            .when((uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(pl.lit(_SA_SHARED_RW["mdb_unrated"]))
        )

        chain = _b31_append_institution_maturity_branches(chain, uc)

        # Corporate / retail / misc tail of the chain.
        is_unrated_corporate = (
            uc.str.contains("CORPORATE", literal=True)
            & ~uc.str.contains("SME", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
        )
        exposures = exposures.with_columns(
            chain
            # Investment-grade assessment (Art. 122(6)/(8)) — only active under
            # use_investment_grade_assessment. IG -> 65%, non-IG -> 135%.
            .when(
                pl.lit(config.use_investment_grade_assessment)
                & is_unrated_corporate
                & (pl.col("cp_is_investment_grade").fill_null(False) == True)  # noqa: E712
            )
            .then(pl.lit(_SA_B31_RW["corporate_ig"]))
            .when(
                pl.lit(config.use_investment_grade_assessment)
                & is_unrated_corporate
                & (pl.col("cp_is_investment_grade").fill_null(False) != True)  # noqa: E712
            )
            .then(pl.lit(_SA_B31_RW["corporate_nig"]))
            # SME managed as retail: 75% (Art. 123, aggregated <= EUR 1m).
            .when(
                uc.str.contains("SME", literal=True)
                & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
                & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            )
            .then(pl.lit(_SA_SHARED_RW["retail"]))
            # SA Specialised Lending — unrated only (Art. 122A-122B). Rated SL
            # exposures use the corporate CQS table (Art. 122A(3)).
            .when(
                (
                    uc.str.contains("SPECIALISED", literal=True)
                    | (pl.col("sl_type").fill_null("").str.len_chars() > 0)
                )
                & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
            )
            .then(b31_sa_sl_rw_expr())
            # Corporate SME: 85% (CRE20.47-49).
            .when(uc.str.contains("CORPORATE", literal=True) & uc.str.contains("SME", literal=True))
            .then(pl.lit(_SA_B31_RW["corporate_sme"]))
            # QRRE transactor: 45% (Art. 123(2)).
            .when(
                uc.str.contains("RETAIL", literal=True)
                & pl.col("is_qrre_transactor").fill_null(False)
            )
            .then(pl.lit(0.45))
            # Payroll/pension loans: 35% (Art. 123(3)(a-b)).
            .when(
                uc.str.contains("RETAIL", literal=True) & pl.col("is_payroll_loan").fill_null(False)
            )
            .then(pl.lit(0.35))
            # Non-regulatory retail (fails Art. 123A criteria): 100%.
            .when(
                uc.str.contains("RETAIL", literal=True)
                & (pl.col("qualifies_as_retail").fill_null(True) == False)  # noqa: E712
            )
            .then(pl.lit(1.0))
            # Regulatory retail (non-mortgage): 75% flat.
            .when(uc.str.contains("RETAIL", literal=True))
            .then(pl.lit(_SA_SHARED_RW["retail"]))
            # Unrated covered bonds: derive from issuer institution RW
            # (Art. 129(5)). ECRA (rated issuer, cp_institution_cqs) checked
            # first, then SCRA (unrated issuer, cp_scra_grade) as fallback.
            .when(
                uc.str.contains("COVERED_BOND", literal=True)
                & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
            )
            .then(_b31_unrated_cb_rw_expr())
            # High-risk items (Art. 128): VC, PE, speculative RE, etc.
            .when(uc == "HIGH_RISK")
            .then(pl.lit(_SA_B31_RW["high_risk"]))
            # Other Items (Art. 134): sub-type-specific risk weights.
            .when(
                (uc == "OTHER")
                & (pl.col("cp_entity_type").fill_null("").is_in(["other_cash", "other_gold"]))
            )
            .then(pl.lit(_SA_SHARED_RW["other_cash"]))
            .when(
                (uc == "OTHER")
                & (pl.col("cp_entity_type").fill_null("") == "other_items_in_collection")
            )
            .then(pl.lit(_SA_SHARED_RW["other_collection"]))
            .when(
                (uc == "OTHER") & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease")
            )
            .then(
                pl.lit(1.0) / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0)
            )
            .when(uc == "OTHER")
            .then(pl.lit(_SA_SHARED_RW["other_default"]))
            # Equity (Art. 133(3)): 250% — full equity treatment (CIU,
            # transitional floor) lives in the dedicated equity table.
            .when(uc == "EQUITY")
            .then(pl.lit(2.50))
            .otherwise(pl.col("risk_weight").fill_null(1.0))
            .alias("risk_weight")
        )
        return exposures

    def _apply_crr_risk_weight_overrides(
        self,
        exposures: pl.LazyFrame,
        uc: pl.Expr,
        is_domestic_currency: pl.Expr,
    ) -> pl.LazyFrame:
        """Apply CRR class-specific risk-weight overrides (Art. 112-134)."""
        chain = (
            # Art. 114(3)/(4): Domestic CGCB -> 0% RW (overrides all CQS).
            pl.when(uc.str.contains("CENTRAL_GOVT", literal=True) & is_domestic_currency)
            .then(pl.lit(0.0))
            # QCCP trade exposures (CRR Art. 306, CRE54.14-15).
            .when(pl.col("cp_entity_type") == "ccp")
            .then(
                pl.when(pl.col("cp_is_ccp_client_cleared").fill_null(False))
                .then(pl.lit(_SA_SHARED_RW["qccp_client_cleared"]))
                .otherwise(pl.lit(_SA_SHARED_RW["qccp_proprietary"]))
            )
        )

        chain = _crr_append_real_estate_branches(chain, uc)

        # SME / retail branches.
        chain = (
            # SME managed as retail: 75% (CRR Art. 123, aggregated <= EUR 1m).
            chain.when(
                uc.str.contains("SME", literal=True)
                & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
                & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            )
            .then(pl.lit(_SA_SHARED_RW["retail"]))
            # Corporate SME: 100%.
            .when(uc.str.contains("CORPORATE", literal=True) & uc.str.contains("SME", literal=True))
            .then(pl.lit(1.0))
            # Non-regulatory retail (fails qualifying criteria): 100%.
            .when(
                uc.str.contains("RETAIL", literal=True)
                & (pl.col("qualifies_as_retail").fill_null(True) == False)  # noqa: E712
            )
            .then(pl.lit(1.0))
            # Regulatory retail (non-mortgage): 75% flat.
            .when(uc.str.contains("RETAIL", literal=True))
            .then(pl.lit(_SA_SHARED_RW["retail"]))
        )

        # Sovereign-like (PSE, RGLA, MDB, IO).
        chain = (
            # PSE short-term (Art. 116(3)): original maturity <= 3m -> 20%.
            chain.when(
                (uc == "PSE")
                & pl.col("original_maturity_years").is_not_null()
                & (pl.col("original_maturity_years") <= 0.25)
            )
            .then(pl.lit(_SA_SHARED_RW["pse_short_term"]))
            # PSE unrated: sovereign-derived (Art. 116(1), Table 2).
            .when((uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(
                pl.when(pl.col("cp_country_code") == "GB")
                .then(pl.lit(0.20))
                .otherwise(pl.lit(_SA_SHARED_RW["pse_unrated"]))
            )
            # RGLA UK devolved govt -> 0% (PRA designation).
            .when(
                (uc == "RGLA")
                & (pl.col("cp_entity_type").fill_null("") == "rgla_sovereign")
                & (pl.col("cp_country_code") == "GB")
            )
            .then(pl.lit(_SA_SHARED_RW["rgla_uk_devolved"]))
            # RGLA domestic currency -> 20% (Art. 115(5)).
            .when((uc == "RGLA") & is_domestic_currency)
            .then(pl.lit(_SA_SHARED_RW["rgla_domestic"]))
            # RGLA unrated non-domestic: sovereign-derived (Table 1A).
            .when((uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(
                pl.when(pl.col("cp_country_code") == "GB")
                .then(pl.lit(0.20))
                .otherwise(pl.lit(_SA_SHARED_RW["rgla_unrated"]))
            )
            # Named MDB -> 0% (Art. 117(2)).
            .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
            .then(pl.lit(_SA_SHARED_RW["mdb_named"]))
            # International Organisation -> 0% (Art. 118).
            .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "international_org"))
            .then(pl.lit(_SA_SHARED_RW["io"]))
            # Unrated non-named MDB -> 50% (Art. 117(1), Table 2B).
            .when((uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
            .then(pl.lit(_SA_SHARED_RW["mdb_unrated"]))
        )

        chain = _crr_append_institution_maturity_branches(chain, uc)

        # Covered bond / high risk / other items / equity tail.
        exposures = exposures.with_columns(
            chain
            # Unrated covered bonds: derive from issuer institution RW
            # (CRR Art. 129(5)) via COVERED_BOND_UNRATED_DERIVATION table.
            .when(
                uc.str.contains("COVERED_BOND", literal=True)
                & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
            )
            .then(_crr_unrated_cb_rw_expr())
            # High-risk items (Art. 128).
            .when(uc == "HIGH_RISK")
            .then(pl.lit(_SA_CRR_RW["high_risk"]))
            # Other Items (Art. 134): sub-type-specific risk weights.
            .when(
                (uc == "OTHER")
                & (pl.col("cp_entity_type").fill_null("").is_in(["other_cash", "other_gold"]))
            )
            .then(pl.lit(_SA_SHARED_RW["other_cash"]))
            .when(
                (uc == "OTHER")
                & (pl.col("cp_entity_type").fill_null("") == "other_items_in_collection")
            )
            .then(pl.lit(_SA_SHARED_RW["other_collection"]))
            .when(
                (uc == "OTHER") & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease")
            )
            .then(
                pl.lit(1.0) / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0)
            )
            .when(uc == "OTHER")
            .then(pl.lit(_SA_SHARED_RW["other_default"]))
            # Equity (Art. 133(2)): flat 100%.
            .when(uc == "EQUITY")
            .then(pl.lit(1.00))
            .otherwise(pl.col("risk_weight").fill_null(1.0))
            .alias("risk_weight")
        )
        return exposures

    def _apply_sovereign_floor_for_institutions(
        self,
        exposures: pl.LazyFrame,
        is_domestic_currency_expr: pl.Expr,
    ) -> pl.LazyFrame:
        """
        Apply sovereign RW floor for FX unrated institution exposures.

        Art. 121(6) (CRR) / CRE20.22 (Basel 3.1): The risk weight for an
        unrated institution exposure not denominated in the institution's
        domestic currency cannot be lower than the sovereign risk weight of
        the institution's jurisdiction.

        Exception: Self-liquidating trade-related contingent items arising
        from the movement of goods with original maturity ≤ 1 year are not
        subject to this floor (CRE20.22 footnote 13).

        Requires ``cp_sovereign_cqs`` to be present and non-null on the
        exposure. When absent or null, no floor is applied (backward
        compatible). ``cp_local_currency`` enables accurate FX detection;
        when absent, falls back to the UK/EU domestic currency expression.

        References:
        - CRR Art. 121(6)
        - PRA PS1/26 Art. 121(6)
        - CRE20.22 (Basel 3.1 SCRA sovereign floor)
        """
        _uc = pl.col("_upper_class")

        # Sovereign CQS → risk weight mapping (Art. 114 table)
        _sovereign_rw = (
            pl.when(pl.col("cp_sovereign_cqs") == 1)
            .then(pl.lit(0.0))
            .when(pl.col("cp_sovereign_cqs") == 2)
            .then(pl.lit(0.20))
            .when(pl.col("cp_sovereign_cqs") == 3)
            .then(pl.lit(0.50))
            .when(pl.col("cp_sovereign_cqs").is_in([4, 5]))
            .then(pl.lit(1.0))
            .when(pl.col("cp_sovereign_cqs") == 6)
            .then(pl.lit(1.50))
            .otherwise(pl.lit(None).cast(pl.Float64))
        )

        # Compute sovereign RW as a temporary column
        exposures = exposures.with_columns(_sovereign_rw.alias("_sovereign_rw"))

        # FX detection: exposure currency != institution's domestic currency.
        # Use cp_local_currency if available; fall back to UK/EU domestic check.
        _is_fx = (
            pl.when(pl.col("cp_local_currency").is_not_null())
            .then(pl.col("currency").fill_null("") != pl.col("cp_local_currency"))
            .otherwise(~is_domestic_currency_expr)
        )

        # Exception: self-liquidating trade items ≤ 1yr original maturity
        # (Art. 121(6) CRR / CRE20.22 footnote 13 — both key on ORIGINAL maturity).
        _is_trade_exempt = pl.col("is_short_term_trade_lc").fill_null(False) & (
            pl.col("original_maturity_years").fill_null(5.0) <= 1.0
        )

        # Floor applies to: unrated institution exposures in FX with
        # a known sovereign CQS, excluding trade-exempt items.
        _is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
        _is_institution = _uc.str.contains("INSTITUTION", literal=True)

        _floor_applies = (
            _is_institution
            & _is_unrated
            & _is_fx
            & ~_is_trade_exempt
            & pl.col("_sovereign_rw").is_not_null()
        )

        exposures = exposures.with_columns(
            pl.when(_floor_applies)
            .then(pl.max_horizontal(pl.col("risk_weight"), pl.col("_sovereign_rw")))
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight")
        )

        return exposures

    def _apply_defaulted_risk_weight(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        ead_col: str,
    ) -> pl.LazyFrame:
        """
        Apply Art. 127 defaulted risk weight with secured/unsecured split.

        CRR Art. 127(1)-(2) / CRE20.89-90 require splitting defaulted exposures
        into secured and unsecured portions based on eligible CRM:
        - Secured portion (non-financial collateral): retains the base risk weight
        - Unsecured portion: 100% if provisions >= 20% of unsecured value, else 150%

        Financial collateral already reduces EAD via collateral_adjusted_value
        before this method is called. Non-financial collateral (RE, receivables,
        other physical) provides additional secured coverage that reduces the
        portion subject to the defaulted 100%/150% override.

        When no non-financial collateral is present, the entire exposure gets
        the provision-based 100%/150% (identical to prior behaviour).

        Basel 3.1 exception: non-income-dependent RESI RE defaults always get
        100% flat regardless of provisions or collateral (CRE20.88).

        References:
        - CRR Art. 127(1): unsecured part risk weight (100%/150%)
        - CRR Art. 127(2): secured/unsecured split via eligible CRM
        - CRE20.88: B31 RESI RE non-income flat 100%
        - CRE20.89-90: B31 defaulted provision test and CRM eligibility
        """
        _uc = pl.col("exposure_class").fill_null("").str.to_uppercase()

        # Non-financial collateral coverage (Art. 127(2))
        # Financial collateral already reduced EAD; these are additional
        # non-financial CRM items that define the secured portion.
        non_fin_collateral = (
            pl.col("collateral_re_value").fill_null(0.0)
            + pl.col("collateral_receivables_value").fill_null(0.0)
            + pl.col("collateral_other_physical_value").fill_null(0.0)
        )

        # Secured/unsecured split — guard against zero EAD
        ead = pl.col(ead_col)
        secured_pct = (
            pl.when(ead > 0).then((non_fin_collateral / ead).clip(0.0, 1.0)).otherwise(pl.lit(0.0))
        )
        unsecured_pct = pl.lit(1.0) - secured_pct

        # Compute provision-based defaulted risk weight for the unsecured portion
        if config.is_basel_3_1:
            # B31 RESI RE non-income-dependent: 100% flat for whole exposure (CRE20.88)
            is_resi_re_non_income = (
                _uc.str.contains("MORTGAGE", literal=True)
                | _uc.str.contains("RESIDENTIAL", literal=True)
            ) & ~pl.col("has_income_cover").fill_null(False)

            # B31 provision ratio: provision / unsecured_ead
            unsecured_ead = ead * unsecured_pct
            provision_rw = (
                pl.when(
                    pl.col("provision_allocated")
                    >= _SA_B31_RW["defaulted_threshold"] * unsecured_ead
                )
                .then(pl.lit(_SA_B31_RW["defaulted_high"]))
                .otherwise(pl.lit(_SA_B31_RW["defaulted_low"]))
            )

            # RESI RE non-income: 100% flat for the whole exposure (no split)
            # All other defaulted: blend base RW (secured) + provision RW (unsecured)
            blended_rw = (
                pl.when(is_resi_re_non_income)
                .then(pl.lit(_SA_B31_RW["defaulted_resi_re_non_income"]))
                .otherwise(unsecured_pct * provision_rw + secured_pct * pl.col("risk_weight"))
            )
        else:
            # CRR provision ratio: provision / (unsecured_ead + provision_deducted)
            # Denominator reconstructs pre-provision unsecured value per Art. 127(1)
            unsecured_pre_prov = (ead + pl.col("provision_deducted")) * unsecured_pct
            provision_rw = (
                pl.when(
                    pl.col("provision_allocated")
                    >= _SA_CRR_RW["defaulted_threshold"] * unsecured_pre_prov
                )
                .then(pl.lit(_SA_CRR_RW["defaulted_high"]))
                .otherwise(pl.lit(_SA_CRR_RW["defaulted_low"]))
            )

            # Blend base RW (secured) + provision RW (unsecured)
            blended_rw = unsecured_pct * provision_rw + secured_pct * pl.col("risk_weight")

        # Apply only to defaulted, non-HIGH_RISK exposures
        is_defaulted = pl.col("is_defaulted").fill_null(False) & (_uc != "HIGH_RISK")

        return exposures.with_columns(
            pl.when(is_defaulted)
            .then(blended_rw)
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight")
        )

    def _apply_fcsm_rw_substitution(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
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

        This method is a no-op when the Comprehensive Method is elected (default)
        or when fcsm_collateral_value is zero/absent.

        Args:
            exposures: Exposures with risk_weight and fcsm_* columns.
            config: Calculation configuration.

        Returns:
            Exposures with blended risk weight for FCSM-covered portion.
        """
        if config.crm_collateral_method != CRMCollateralMethod.SIMPLE:
            return exposures

        schema = exposures.collect_schema()
        if "fcsm_collateral_value" not in schema.names():  # arch-exempt: early-exit guard
            return exposures

        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        ead = pl.col(ead_col).fill_null(0.0)
        fcsm_value = pl.col("fcsm_collateral_value").fill_null(0.0)
        fcsm_rw = pl.col("fcsm_collateral_rw").fill_null(0.0)

        # Secured percentage (capped at 100%)
        secured_pct = pl.when(ead > 0).then((fcsm_value / ead).clip(0.0, 1.0)).otherwise(0.0)
        unsecured_pct = pl.lit(1.0) - secured_pct

        # Blended risk weight; secured RW already reflects per-item floor + carve-outs.
        blended_rw = secured_pct * fcsm_rw + unsecured_pct * pl.col("risk_weight")

        # Only apply when there is actual collateral value
        has_fcsm = fcsm_value > 0

        return exposures.with_columns(
            # Save pre-FCSM risk weight for audit
            pl.col("risk_weight").alias("pre_fcsm_risk_weight"),
            # Apply blended RW
            pl.when(has_fcsm)
            .then(blended_rw)
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
            # Track method for audit/COREP
            pl.when(has_fcsm)
            .then(pl.lit("simple"))
            .otherwise(pl.lit("comprehensive"))
            .alias("ead_calculation_method"),
        )

    @staticmethod
    def _apply_life_insurance_rw_mapping(
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Apply Art. 232 life insurance risk weight mapping for SA exposures.

        When life insurance collateral secures an exposure, the secured portion
        receives a mapped risk weight (not direct substitution):
            Insurer RW 20%           -> 20%
            Insurer RW 30% or 50%    -> 35%
            Insurer RW 65%-135%      -> 70%
            Insurer RW 150%          -> 150%

        Blended RW = secured_pct x mapped_rw + unsecured_pct x exposure_rw

        This method is a no-op when no life insurance collateral is present.

        Args:
            exposures: Exposures with risk_weight and life_ins_* columns.

        Returns:
            Exposures with blended risk weight for life-insurance-covered portion.
        """
        schema = exposures.collect_schema()
        if "life_ins_collateral_value" not in schema.names():  # arch-exempt: early-exit guard
            return exposures

        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        ead = pl.col(ead_col).fill_null(0.0)
        li_value = pl.col("life_ins_collateral_value").fill_null(0.0)
        li_rw = pl.col("life_ins_secured_rw").fill_null(0.0)

        # Secured percentage (capped at 100%)
        secured_pct = pl.when(ead > 0).then((li_value / ead).clip(0.0, 1.0)).otherwise(0.0)
        unsecured_pct = pl.lit(1.0) - secured_pct

        # Blended risk weight: no floor — Art. 232 has no 20% floor like FCSM
        blended_rw = secured_pct * li_rw + unsecured_pct * pl.col("risk_weight")

        # Only apply when there is actual life insurance collateral
        has_li = li_value > 0

        return exposures.with_columns(
            pl.when(has_li).then(blended_rw).otherwise(pl.col("risk_weight")).alias("risk_weight"),
        )

    def _apply_guarantee_substitution(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution for unfunded credit protection.

        For guaranteed portions, the risk weight is substituted with the
        guarantor's risk weight. The final RWA is calculated using blended
        risk weight based on guaranteed vs unguaranteed portions.

        CRR Art. 213-217: Unfunded credit protection

        Args:
            exposures: Exposures with risk_weight and guarantee columns
            config: Calculation configuration

        Returns:
            Exposures with guarantee substitution applied
        """
        cols = exposures.collect_schema().names()

        # Return early when no guarantee data is present.
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

        # Art. 114(3)/(4) domestic CGCB-guarantor currency check.
        is_domestic_guarantor = _build_domestic_guarantor_expr(exposures.collect_schema().names())

        # Look up guarantor's RW based on exposure class + CQS.
        exposures = exposures.with_columns(
            _build_guarantor_rw_expr(is_domestic_guarantor, config.is_basel_3_1).alias(
                "guarantor_rw"
            ),
        )

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
        ead_col = "ead_final" if "ead_final" in cols else "ead"

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
                    / pl.col(ead_col)
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

    def _apply_currency_mismatch_multiplier(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply 1.5x RW multiplier for retail/RE currency mismatch (Basel 3.1 only).

        When the exposure currency differs from the borrower's income currency,
        a 1.5x multiplier is applied to the risk weight for retail and real estate
        exposure classes.

        Basel 3.1 Art. 123B / CRE20.93.

        Args:
            exposures: Exposures with risk_weight and currency columns
            config: Calculation configuration

        Returns:
            Exposures with currency mismatch multiplier applied where applicable
        """
        if not config.is_basel_3_1:
            return exposures

        schema = exposures.collect_schema()
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
            return exposures

        _uc = (
            pl.col("_upper_class")
            if "_upper_class" in cols
            else (pl.col("exposure_class").fill_null("").str.to_uppercase())
        )

        is_retail_or_re = (
            _uc.str.contains("RETAIL", literal=True)
            | _uc.str.contains("MORTGAGE", literal=True)
            | _uc.str.contains("RESIDENTIAL", literal=True)
            | _uc.str.contains("COMMERCIAL", literal=True)
            | _uc.str.contains("CRE", literal=True)
        )

        has_mismatch = pl.col(income_col).is_not_null() & (pl.col(income_col) != pl.col("currency"))

        mismatch_applies = is_retail_or_re & has_mismatch

        exposures = exposures.with_columns(
            [
                pl.when(mismatch_applies)
                .then((pl.col("risk_weight") * 1.5).clip(upper_bound=pl.lit(1.50)))
                .otherwise(pl.col("risk_weight"))
                .alias("risk_weight"),
                mismatch_applies.alias("currency_mismatch_multiplier_applied"),
            ]
        )

        return exposures

    def _apply_due_diligence_override(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Apply due diligence risk weight override (Basel 3.1 Art. 110A).

        Under Basel 3.1, firms must perform due diligence on all SA exposures.
        Where due diligence reveals that the risk weight does not adequately
        reflect the risk, the firm must apply a higher risk weight.

        The override only increases the risk weight — it can never reduce it.
        This is applied as the final risk weight modification before RWA
        calculation, after all standard RW determination, CRM, and currency
        mismatch adjustments.

        Args:
            exposures: Exposures with risk_weight column
            config: Calculation configuration
            errors: Optional error list to append warnings to

        Returns:
            Exposures with due diligence override applied where applicable
        """
        if not config.is_basel_3_1:
            return exposures

        schema = exposures.collect_schema()
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
            return exposures

        override_applies = pl.col("due_diligence_override_rw").is_not_null() & (
            pl.col("due_diligence_override_rw") > pl.col("risk_weight")
        )

        exposures = exposures.with_columns(
            [
                pl.when(override_applies)
                .then(pl.col("due_diligence_override_rw"))
                .otherwise(pl.col("risk_weight"))
                .alias("risk_weight"),
                override_applies.alias("due_diligence_override_applied"),
            ]
        )

        return exposures

    @staticmethod
    def _warn_equity_in_main_table(
        exposures: pl.LazyFrame,
        errors: list[CalculationError],
    ) -> None:
        """Emit SA005 info if equity-class rows may be in main exposure table.

        Equity exposures in the main loan/contingent tables receive correct SA
        equity risk weights (250% Basel 3.1, 100% CRR) but miss full equity
        treatment available via the dedicated equity_exposures input table:
        CIU look-through/mandate-based approaches, transitional floor schedule,
        type-specific weights (central_bank 0%, subordinated_debt 150%,
        speculative 400%), and IRB Simple method (CRR).

        The check is based on the approach column containing equity values,
        which is set by the classifier for equity-class rows.
        """
        schema = exposures.collect_schema()
        if "approach" not in schema.names():  # arch-exempt: early-exit guard
            return
        # Approach == "equity" is only set for equity-class rows from the main
        # tables. We detect this via a lightweight one-row collect to avoid
        # materialising the full frame.
        has_equity = (
            exposures.filter(pl.col("approach") == ApproachType.EQUITY.value)
            .head(1)
            .collect()
            .height
            > 0
        )
        if has_equity:
            errors.append(
                CalculationError(
                    code=ERROR_EQUITY_IN_MAIN_TABLE,
                    message=(
                        "Equity-class exposures detected in main exposure table. "
                        "These receive default SA equity risk weights (250% Basel 3.1 "
                        "Art. 133(3), 100% CRR Art. 133(2)). For type-specific weights "
                        "(central_bank 0%, subordinated_debt 150%, speculative 400%), "
                        "CIU approaches, transitional floor, or IRB Simple, "
                        "use the dedicated equity_exposures input table."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference="CRR Art. 133 / PRA PS1/26 Art. 133",
                    field_name="exposure_class",
                )
            )


def create_sa_calculator() -> SACalculator:
    """
    Create an SA calculator instance.

    Returns:
        SACalculator ready for use
    """
    return SACalculator()
