"""
Standardised Approach base risk-weight assignment.

Plain typed functions implementing the SA risk-weight lookup chain — CQS
table join, framework-specific class overrides (CRR Art. 112-134 vs PRA
PS1/26 / CRE20), the sovereign floor for FX unrated institutions, and the
Art. 127 defaulted treatment. ``SACalculator`` composes ``apply_risk_weights``
via ``LazyFrame.pipe``; the CRM processor reuses it for the link-ranking
SA-RW preview.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- SA input contract defaults (``SA_INPUT_CONTRACT``)
- CQS-table risk-weight join + framework override chains (CRR / Basel 3.1)
- Sovereign-derived lookups (PSE / RGLA / MDB), ECA/MEIP scores, covered-bond
  unrated derivation
- Art. 121(6) / CRE20.22 sovereign floor for FX unrated institutions
- Art. 127 defaulted risk weights

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 127: Defaulted exposure risk weights
- CRR Art. 137: ECA / MEIP sovereign risk weights
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

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    CLASSIFIER_OUTPUT_SCHEMA,
    CRM_OUTPUT_SCHEMA,
    HIERARCHY_OUTPUT_SCHEMA,
)
from rwa_calc.data.tables.b31_equity_rw import B31_SA_EQUITY_RISK_WEIGHTS
from rwa_calc.data.tables.b31_risk_weights import (
    B31_CORPORATE_INVESTMENT_GRADE_RW,
    B31_CORPORATE_NON_INVESTMENT_GRADE_RW,
    B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS,
    B31_CORPORATE_SME_RW,
    B31_COVERED_BOND_UNRATED_FROM_SCRA,
    B31_CURRENCY_MISMATCH_HEDGE_COVERAGE_FLOOR,
    B31_CURRENCY_MISMATCH_MULTIPLIER,
    B31_CURRENCY_MISMATCH_RW_CAP,
    B31_DEFAULTED_PROVISION_THRESHOLD,
    B31_DEFAULTED_RESI_RE_NON_INCOME_RW,
    B31_DEFAULTED_RW_HIGH_PROVISION,
    B31_DEFAULTED_RW_LOW_PROVISION,
    B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS,
    B31_ECRA_SHORT_TERM_RISK_WEIGHTS,
    B31_HIGH_RISK_RW,
    B31_RETAIL_NON_REGULATORY_RW,
    B31_RETAIL_PAYROLL_LOAN_RW,
    B31_RETAIL_TRANSACTOR_RW,
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
from rwa_calc.data.tables.crr_equity_rw import SA_EQUITY_RISK_WEIGHTS as CRR_SA_EQUITY_RW
from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    COMMERCIAL_RE_PARAMS,
    CORPORATE_RISK_WEIGHTS,
    COVERED_BOND_UNRATED_DERIVATION,
    COVERED_BOND_UNRATED_DERIVATION_CRR,
    CRR_CORPORATE_SME_RW,
    CRR_DEFAULTED_PROVISION_THRESHOLD,
    CRR_DEFAULTED_RW_HIGH_PROVISION,
    CRR_DEFAULTED_RW_LOW_PROVISION,
    CRR_NON_REGULATORY_RETAIL_RW,
    ECA_MEIP_RISK_WEIGHTS,
    HIGH_RISK_RW,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
    INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_UNRATED_RW_CRR,
    IO_ZERO_RW,
    MDB_NAMED_ZERO_RW,
    MDB_UNRATED_RW,
    OTHER_ITEMS_CASH_RW,
    OTHER_ITEMS_COLLECTION_RW,
    OTHER_ITEMS_DEFAULT_RW,
    PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    PSE_SHORT_TERM_RW,
    PSE_UNRATED_DEFAULT_RW,
    QCCP_CLIENT_CLEARED_RW,
    QCCP_PROPRIETARY_RW,
    RESIDENTIAL_MORTGAGE_PARAMS,
    RETAIL_RISK_WEIGHT,
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    RGLA_UK_DEVOLVED_RW,
    RGLA_UNRATED_DEFAULT_RW,
    build_institution_guarantor_rw_expr,
    get_combined_cqs_risk_weights,
)
from rwa_calc.data.tables.eu_sovereign import (
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.domain.enums import CQS, EquityType
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from polars.expr.whenthen import ChainedThen, Then

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# In-progress when/then chain accepted/extended by the branch appenders.
type _RWChain = Then | ChainedThen


# =============================================================================
# SA INPUT CONTRACT
# Defensive defaults for columns the SA pipeline reads. Composed of
# stage-output schemas (hierarchy / CRM / classifier) plus a small set of
# input-schema columns that may be absent when calculators are invoked
# directly from tests or ad-hoc pipelines.
# =============================================================================

SA_INPUT_CONTRACT: dict[str, ColumnSpec] = {
    **HIERARCHY_OUTPUT_SCHEMA,
    **CRM_OUTPUT_SCHEMA,
    **CLASSIFIER_OUTPUT_SCHEMA,
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "property_type": ColumnSpec(pl.String, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "is_adc": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_presold": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qualifying_re": ColumnSpec(pl.Boolean, required=False),
    "prior_charge_ltv": ColumnSpec(pl.Float64, default=0.0, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    "has_short_term_ecai": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qrre_transactor": ColumnSpec(pl.Boolean, default=False, required=False),
    "sl_type": ColumnSpec(pl.String, required=False),
    "life_ins_collateral_value": ColumnSpec(pl.Float64, required=False),
    "life_ins_secured_rw": ColumnSpec(pl.Float64, required=False),
    # Null default: the crm_exit edge always carries the real ead_gross in
    # production; B31 defaulted-RW tests that exercise the provision
    # threshold must supply it explicitly.
    "ead_gross": ColumnSpec(pl.Float64, required=False),
}


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
    # Corporate / retail / equity tail (Art. 122 / 123 / 133(2))
    "corporate_sme": float(CRR_CORPORATE_SME_RW),
    "non_reg_retail": float(CRR_NON_REGULATORY_RETAIL_RW),
    "equity": float(CRR_SA_EQUITY_RW[EquityType.LISTED]),
}

# Basel 3.1 specific scalars (PRA PS1/26, CRE20).
_SA_B31_RW: dict[str, float] = {
    "high_risk": float(B31_HIGH_RISK_RW),
    # ECRA short-term institution weights (Table 4) — three-way split
    # CQS 1-3 = 20%, CQS 4-5 = 50%, CQS 6 = 150% (PRA PS1/26 Art. 120(2)).
    "ecra_st_low": float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[1]),
    "ecra_st_mid": float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[4]),
    "ecra_st_high": float(B31_ECRA_SHORT_TERM_RISK_WEIGHTS[6]),
    # Table 4A (PRA PS1/26 Art. 120(2B)) — dedicated short-term ECAI assessment.
    # CQS 1=20%, CQS 2=50%, CQS 3=100%, CQS 4-5=150%.
    "ecra_st_ecai_cqs1": float(B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS[1]),
    "ecra_st_ecai_cqs2": float(B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS[2]),
    "ecra_st_ecai_cqs3": float(B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS[3]),
    "ecra_st_ecai_high": float(B31_ECRA_SHORT_TERM_ECAI_RISK_WEIGHTS[4]),
    # Table 6A (PRA PS1/26 Art. 122(3)) — corporate dedicated short-term ECAI.
    # CQS 1=20%, CQS 2=50%, CQS 3=100%, CQS 4-6/Others=150%.
    "corp_st_ecai_cqs1": float(B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS[1]),
    "corp_st_ecai_cqs2": float(B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS[2]),
    "corp_st_ecai_cqs3": float(B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS[3]),
    "corp_st_ecai_high": float(B31_CORPORATE_SHORT_TERM_ECAI_RISK_WEIGHTS[4]),
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
    # Retail / equity tail (PRA PS1/26 Art. 123 / Art. 133(3))
    "qrre_transactor": float(B31_RETAIL_TRANSACTOR_RW),
    "payroll": float(B31_RETAIL_PAYROLL_LOAN_RW),
    "non_reg_retail": float(B31_RETAIL_NON_REGULATORY_RW),
    "equity": float(B31_SA_EQUITY_RISK_WEIGHTS[EquityType.LISTED]),
    # Currency mismatch (PRA PS1/26 Art. 123B / CRE20.93)
    "currency_mismatch_multiplier": float(B31_CURRENCY_MISMATCH_MULTIPLIER),
    "currency_mismatch_cap": float(B31_CURRENCY_MISMATCH_RW_CAP),
    # PRA PS1/26 Art. 123B(2): partial-hedge coverage threshold (>= 0.90 waives)
    "currency_mismatch_hedge_floor": float(B31_CURRENCY_MISMATCH_HEDGE_COVERAGE_FLOOR),
    # B31 Art. 129(5) covered-bond unrated SCRA fallback (Grade C equivalent)
    "unrated_cb_default": float(B31_COVERED_BOND_UNRATED_FROM_SCRA["C"]),
}


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


@cites("CRR Art. 112")
def apply_risk_weights(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Look up and apply risk weights based on exposure class.

    Orchestrates the three-phase SA risk weight assignment:
        1. Setup — ensure columns, derive maturity, classify, join CQS table
        2. Framework-specific when/then overrides (CRR vs Basel 3.1)
        3. Cleanup — sovereign floor, defaulted RW blending, drop temp cols

    Branches in the override chain are order-sensitive (first match wins);
    the framework override helpers apply them in the sequence prescribed
    by the regulation.
    """
    exposures, uc, is_domestic_currency = _prepare_risk_weight_lookup(lf, config, pack=pack)

    if config.is_basel_3_1:
        exposures = _apply_b31_risk_weight_overrides(exposures, uc, is_domestic_currency, config)
    else:
        exposures = _apply_crr_risk_weight_overrides(exposures, uc, is_domestic_currency)

    # Art. 121(6) (CRR) / CRE20.22 (Basel 3.1): Sovereign RW floor for
    # FX-denominated unrated institution exposures. Exception:
    # self-liquidating trade items with original maturity <= 1yr.
    exposures = _apply_sovereign_floor_for_institutions(exposures, is_domestic_currency)

    # Art. 127 defaulted risk weight (secured/unsecured split). Runs after
    # the base RW when-chain so defaulted exposures have their non-defaulted
    # base RW available for blending with collateral coverage.
    exposures = _apply_defaulted_risk_weight(exposures, config, pack=pack)

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


# ---------------------------------------------------------------------------
# Sovereign-derived risk-weight helpers (PSE Art. 116(1) Table 2 /
# RGLA Art. 115(1)(a) Table 1A)
# ---------------------------------------------------------------------------


def _sovereign_derived_rw_expr(
    table: dict[CQS, Decimal],
    unrated_default: float,
) -> pl.Expr:
    """Build Polars expression for sovereign-CQS-derived RW lookup.

    Used for unrated PSEs (Art. 116(1) Table 2) and unrated non-domestic
    RGLAs (Art. 115(1)(a) Table 1A). Both tables map sovereign CQS (1-6) to
    a risk weight; when ``cp_sovereign_cqs`` is null/unknown, the
    conservative ``unrated_default`` (100%) is applied.

    References:
        CRR Art. 116(1) Table 2 — sovereign-derived PSE risk weights
        CRR Art. 115(1)(a) Table 1A — sovereign-derived RGLA risk weights
        PRA PS1/26 Art. 116 / 115 (identical values)
    """
    cqs_order: list[CQS] = [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]
    expr = pl.when(pl.col("cp_sovereign_cqs") == int(cqs_order[0])).then(
        pl.lit(float(table[cqs_order[0]]))
    )
    for cqs_val in cqs_order[1:]:
        expr = expr.when(pl.col("cp_sovereign_cqs") == int(cqs_val)).then(
            pl.lit(float(table[cqs_val]))
        )
    return expr.otherwise(pl.lit(unrated_default))


def _cqs_table_lookup_expr(
    cqs_col: str,
    table: dict[CQS, Decimal],
    unrated_default: pl.Expr | float,
) -> pl.Expr:
    """Build a when/then chain mapping a CQS-bearing column to RW from a CQS table.

    Mirrors the structure of ``_sovereign_derived_rw_expr`` but parameterised
    on the CQS source column so it can drive any CQS-keyed regulatory table
    (CGCB Art. 114, MDB Table 2B Art. 117(1), PSE Table 2A Art. 116(2),
    RGLA Table 1B Art. 115(1)(b), Corporate Art. 122). Caller controls the
    unrated fallback (constant or Polars expression).
    """
    cqs_order: list[CQS] = [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]
    expr = pl.when(pl.col(cqs_col) == int(cqs_order[0])).then(pl.lit(float(table[cqs_order[0]])))
    for cqs_val in cqs_order[1:]:
        expr = expr.when(pl.col(cqs_col) == int(cqs_val)).then(pl.lit(float(table[cqs_val])))
    if isinstance(unrated_default, pl.Expr):
        return expr.otherwise(unrated_default)
    return expr.otherwise(pl.lit(unrated_default))


# ---------------------------------------------------------------------------
# ECA / MEIP direct sovereign RW (CRR Art. 137(1)-(2) Table 9)
# ---------------------------------------------------------------------------


@cites("CRR Art. 137")
def _eca_meip_rw_expr() -> pl.Expr:
    """Build Polars expression mapping ``cp_eca_score`` (0-7) to sovereign RW.

    Maps directly to ``ECA_MEIP_RISK_WEIGHTS`` per CRR Art. 137(2) Table 9 —
    no intermediate CQS step. When ``cp_eca_score`` is null or out of range
    the expression returns null so callers can defer to the standard
    Art. 114 unrated fallback.
    """
    col = pl.col("cp_eca_score")
    expr = pl.when(col == 0).then(pl.lit(float(ECA_MEIP_RISK_WEIGHTS[0])))
    for score in range(1, 8):
        expr = expr.when(col == score).then(pl.lit(float(ECA_MEIP_RISK_WEIGHTS[score])))
    return expr.otherwise(pl.lit(None, dtype=pl.Float64))


# ---------------------------------------------------------------------------
# Covered bond unrated derivation helpers (CRR Art. 129(5))
# ---------------------------------------------------------------------------


@cites("CRR Art. 129")
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

    # Pre-compute CQS → CB RW by chaining institution RW through the derivation table.
    # CRR Art. 129(5) admits only four sub-paragraphs (a)-(d); use the CRR-specific
    # 4-key dict so (b) maps 0.50 -> 0.20, not the B31 value 0.25.
    cqs_to_cb_rw: dict[int, float] = {}
    for cqs_val in [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
        inst_rw = inst_table[cqs_val]
        cb_rw = COVERED_BOND_UNRATED_DERIVATION_CRR[inst_rw]
        cqs_to_cb_rw[int(cqs_val)] = float(cb_rw)

    # Unrated institution: sovereign-derived
    unrated_inst_rw = inst_table[CQS.UNRATED]
    unrated_cb_rw = float(COVERED_BOND_UNRATED_DERIVATION_CRR[unrated_inst_rw])

    # Build when/then chain from cp_institution_cqs
    expr = pl.when(pl.col("cp_institution_cqs") == 1).then(pl.lit(cqs_to_cb_rw[1]))
    for cqs_int in [2, 3, 4, 5, 6]:
        expr = expr.when(pl.col("cp_institution_cqs") == cqs_int).then(
            pl.lit(cqs_to_cb_rw[cqs_int])
        )
    # Fallback: cp_institution_cqs is null (unrated institution) or unexpected value
    return expr.otherwise(pl.lit(unrated_cb_rw))


@cites("CRR Art. 129")
@cites("PS1/26, paragraph 129")
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
    # Conservative default: Grade C equivalent (B31_COVERED_BOND_UNRATED_FROM_SCRA["C"])
    return expr.otherwise(pl.lit(_SA_B31_RW["unrated_cb_default"]))


# ---------------------------------------------------------------------------
# Chain-appender helpers for the risk-weight when/then expression.
#
# Each function takes an in-progress ``pl.when(...)..then(...)`` chain and
# appends a themed group of branches (real estate, institutions, etc.),
# returning the extended chain. ORDER of branches within a chain matters —
# the first matching ``.when()`` wins — so the framework override methods
# call these in the sequence prescribed by the regulation.
# ---------------------------------------------------------------------------


def _is_commercial_re_class(uc: pl.Expr) -> pl.Expr:
    """Match commercial real-estate exposures by class string or property_type.

    Used by the SA RE dispatchers and the Art. 127(3) defaulted-RESI rule
    to route ahead of the residential branch — ``COMMERCIAL_MORTGAGE``
    contains the ``MORTGAGE`` substring, so the residential dispatch
    would otherwise grab it.
    """
    return (
        uc.str.contains("COMMERCIAL", literal=True)
        | uc.str.contains("CRE", literal=True)
        | (pl.col("property_type").fill_null("") == "commercial")
    )


def _is_residential_re_class(uc: pl.Expr) -> pl.Expr:
    """Match residential RE — relies on commercial being routed first."""
    return uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True)


@cites("PS1/26, paragraph 128")
def _b31_append_high_risk_branch(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append Basel 3.1 Art. 128 high-risk items branch (150% flat).

    Items associated with particularly high risk — venture capital, private
    equity, speculative immovable property financing, and other
    PRA-designated high-risk items — receive a 150% risk weight under
    PRA PS1/26 Art. 128. CRR has no parallel branch: Art. 128 was omitted
    from UK CRR by SI 2021/1078 reg. 6(3)(a) effective 1 January 2022, so
    HIGH_RISK exposures fall through to the residual OTHER class (100%)
    on the CRR path.
    """
    return chain.when(uc == "HIGH_RISK").then(pl.lit(_SA_B31_RW["high_risk"]))


@cites("PS1/26, paragraph 123")
def _b31_append_retail_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append Basel 3.1 retail-class risk-weight branches (Art. 123).

    Covers the regulatory retail class only (uc contains "RETAIL"):
    - QRRE transactor: 45% (Art. 123(2)).
    - Payroll/pension loans: 35% (Art. 123(4)).
    - Non-regulatory retail (fails Art. 123A criteria): 100% (Art. 123(3)(c)).
    - Regulatory retail (non-mortgage): 75% flat.

    The SME-managed-as-retail and corporate-SME branches stay in the parent
    override (they gate on SME class membership rather than RETAIL).
    """
    return (
        # QRRE transactor: 45% (Art. 123(2)).
        chain.when(
            uc.str.contains("RETAIL", literal=True) & pl.col("is_qrre_transactor").fill_null(False)
        )
        .then(pl.lit(_SA_B31_RW["qrre_transactor"]))
        # Payroll/pension loans: 35% (Art. 123(4)).
        .when(uc.str.contains("RETAIL", literal=True) & pl.col("is_payroll_loan").fill_null(False))
        .then(pl.lit(_SA_B31_RW["payroll"]))
        # Non-regulatory retail (fails Art. 123A criteria): 100%.
        .when(
            uc.str.contains("RETAIL", literal=True)
            & (pl.col("qualifies_as_retail").fill_null(False) == False)  # noqa: E712
        )
        .then(pl.lit(_SA_B31_RW["non_reg_retail"]))
        # Regulatory retail (non-mortgage): 75% flat.
        .when(uc.str.contains("RETAIL", literal=True))
        .then(pl.lit(_SA_SHARED_RW["retail"]))
    )


@cites("PS1/26, paragraph 124")
def _b31_append_real_estate_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append Basel 3.1 real-estate branches (ADC / other-RE / CRE / resi)."""
    is_re_class = (
        _is_commercial_re_class(uc)
        | _is_residential_re_class(uc)
        | (pl.col("property_type").fill_null("").is_in(["residential", "commercial"]))
    )
    is_non_qualifying = pl.col("is_qualifying_re").fill_null(True) == False  # noqa: E712
    return (
        chain.when(pl.col("is_adc").fill_null(False))
        .then(b31_adc_rw_expr())
        # Art. 124J: non-qualifying RE that fails Art. 124A criteria.
        # Null is_qualifying_re defaults to qualifying — backward compatible.
        .when(is_non_qualifying & is_re_class)
        .then(b31_other_re_rw_expr("_cqs_risk_weight"))
        # Commercial RE must precede residential — see _is_commercial_re_class.
        .when(_is_commercial_re_class(uc))
        .then(b31_commercial_rw_expr("_cqs_risk_weight"))
        .when(_is_residential_re_class(uc))
        .then(b31_residential_rw_expr("_cqs_risk_weight"))
    )


def _b31_append_institution_maturity_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append Basel 3.1 ECRA / SCRA institution maturity branches."""
    is_institution = uc.str.contains("INSTITUTION", literal=True)
    is_rated = pl.col("cqs").is_not_null() & (pl.col("cqs") > 0)
    is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
    original_mty = pl.col("original_maturity_years").fill_null(1.0)
    has_st_ecai = pl.col("has_short_term_ecai").fill_null(False)
    in_st_window = (original_mty <= 0.25) | (
        pl.col("is_short_term_trade_lc").fill_null(False) & (original_mty <= 0.5)
    )
    return (
        # ECRA short-term rated institutions with a dedicated short-term ECAI
        # assessment (Table 4A, PRA PS1/26 Art. 120(2B)).
        # CQS 1 = 20%, CQS 2 = 50%, CQS 3 = 100%, CQS 4-5 = 150%.
        #
        # ``has_short_term_ecai`` is derived per-exposure from the rating row
        # (issue-specific Art. 120(2B) ECAI assessment). When the flag fires
        # the engine routes via Table 4A regardless of the original-maturity
        # gate — the producer is responsible for only flagging rating rows
        # whose underlying exposure satisfies the ≤3m / ≤6m maturity rule.
        chain.when(is_institution & is_rated & has_st_ecai)
        .then(
            pl.when(pl.col("cqs") == 1)
            .then(pl.lit(_SA_B31_RW["ecra_st_ecai_cqs1"]))
            .when(pl.col("cqs") == 2)
            .then(pl.lit(_SA_B31_RW["ecra_st_ecai_cqs2"]))
            .when(pl.col("cqs") == 3)
            .then(pl.lit(_SA_B31_RW["ecra_st_ecai_cqs3"]))
            .otherwise(pl.lit(_SA_B31_RW["ecra_st_ecai_high"]))
        )
        # ECRA short-term rated institutions (Table 4, Art. 120(2)).
        # Keys on ORIGINAL maturity <= 3m -> CQS 1-3 = 20%, CQS 4-5 = 50%,
        # CQS 6 = 150%. Art. 120(2A) extends Table 4 to ORIGINAL maturity
        # <= 6m for exposures arising from the movement of goods.
        .when(is_institution & is_rated & in_st_window)
        .then(
            pl.when(pl.col("cqs") <= 3)
            .then(pl.lit(_SA_B31_RW["ecra_st_low"]))
            .when(pl.col("cqs") <= 5)
            .then(pl.lit(_SA_B31_RW["ecra_st_mid"]))
            .otherwise(pl.lit(_SA_B31_RW["ecra_st_high"]))
        )
        # SCRA short-term unrated institutions (Art. 121(3)):
        # ORIGINAL maturity <= 3m -> Grade A/A_ENHANCED = 20%, B = 50%, C = 150%.
        # Null SCRA grade defaults to Grade C (conservative treatment per
        # PRA PS1/26 Art. 120A).
        # Art. 121(4): the short-term window is extended to ORIGINAL maturity
        # <= 6m for self-liquidating trade-finance LCs, mirroring the ECRA
        # extension at Art. 120(2A) — reuses the same in_st_window gate.
        .when(is_institution & is_unrated & in_st_window)
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


def _b31_append_corporate_maturity_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append Basel 3.1 Art. 122(3) Table 6A short-term corporate ECAI branch.

    Fires for rated CORPORATE exposures that carry a dedicated short-term ECAI
    assessment (``has_short_term_ecai=True``). The flag is derived per-exposure
    from the rating row's ``is_short_term`` indicator (see
    ``HierarchyResolver._apply_short_term_rating_override``) — the producer is
    responsible for only flagging rating rows whose underlying exposure
    satisfies Art. 122(3)'s ≤3m original-maturity rule, so the engine no
    longer re-checks maturity here.

    Excludes SME corporates (which use the dedicated 85% SME RW path) so the
    Table 6A lookup only applies to general corporates rated by an ECAI.
    """
    is_corporate = uc.str.contains("CORPORATE", literal=True) & ~uc.str.contains(
        "SME", literal=True
    )
    is_rated = pl.col("cqs").is_not_null() & (pl.col("cqs") > 0)
    has_st_ecai = pl.col("has_short_term_ecai").fill_null(False)
    return chain.when(is_corporate & is_rated & has_st_ecai).then(
        pl.when(pl.col("cqs") == 1)
        .then(pl.lit(_SA_B31_RW["corp_st_ecai_cqs1"]))
        .when(pl.col("cqs") == 2)
        .then(pl.lit(_SA_B31_RW["corp_st_ecai_cqs2"]))
        .when(pl.col("cqs") == 3)
        .then(pl.lit(_SA_B31_RW["corp_st_ecai_cqs3"]))
        .otherwise(pl.lit(_SA_B31_RW["corp_st_ecai_high"]))
    )


@cites("CRR Art. 123")
def _crr_append_retail_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append CRR retail-class risk-weight branches (Art. 123).

    Covers the regulatory retail class only (uc contains "RETAIL"):
    - Non-regulatory retail (fails qualifying criteria): 100% (Art. 123(c)).
    - Payroll/pension loans: 35% (CRR Art. 123 second subparagraph, inserted
      by CRR2 Reg. (EU) 2019/876 F68 — scalar identical to PRA PS1/26
      Art. 123(4), reused from ``_SA_B31_RW``).
    - Regulatory retail (non-mortgage): 75% flat (Art. 123).

    The SME-managed-as-retail branch stays in the parent override (it gates
    on SME class membership, not just retail) and the corporate-SME branch
    is non-retail (Art. 122).
    """
    return (
        # Non-regulatory retail (fails qualifying criteria): 100%.
        chain.when(
            uc.str.contains("RETAIL", literal=True)
            & (pl.col("qualifies_as_retail").fill_null(False) == False)  # noqa: E712
        )
        .then(pl.lit(_SA_CRR_RW["non_reg_retail"]))
        # Payroll/pension loans: 35% (CRR Art. 123 second subparagraph,
        # inserted by CRR2 Reg. (EU) 2019/876 F68). Scalar identical to the
        # Basel 3.1 payroll RW (PRA PS1/26 Art. 123(4)), so the same
        # B31_RETAIL_PAYROLL_LOAN_RW constant is reused via _SA_B31_RW.
        .when(uc.str.contains("RETAIL", literal=True) & pl.col("is_payroll_loan").fill_null(False))
        .then(pl.lit(_SA_B31_RW["payroll"]))
        # Regulatory retail (non-mortgage): 75% flat.
        .when(uc.str.contains("RETAIL", literal=True))
        .then(pl.lit(_SA_SHARED_RW["retail"]))
    )


@cites("CRR Art. 124")
def _crr_append_real_estate_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append CRR commercial-then-residential RE branches (Art. 125-126)."""
    ltv_safe = pl.col("ltv").fill_null(1.0)
    # CRR Art. 126(2)(d) proportion split for CRE with income cover and LTV > 50%:
    #   secured_share   = min(1.0, 50% / LTV)  -> portion attracting 50% RW
    #   residual_share  = 1.0 - secured_share  -> portion attracting unsecured
    #                     counterparty RW (Art. 124(1) -> Art. 122 corporate CQS)
    # When LTV <= 50% the clamp drives secured_share = 1.0 so the average collapses
    # to the preferential 50% RW, matching the pre-split behaviour.
    cre_secured_share = pl.min_horizontal(pl.lit(1.0), _SA_CRR_RW["cre_ltv_threshold"] / ltv_safe)
    cre_residual_share = pl.lit(1.0) - cre_secured_share
    # CRR Art. 124(1): the residual leg attracts the counterparty's UNSECURED
    # risk weight, i.e. the Art. 122 corporate CQS lookup — NOT a fixed 100%.
    # Look up counterparty CQS against CORPORATE_RISK_WEIGHTS directly (rather
    # than via the join-derived ``risk_weight``) so the rule still fires when
    # the upstream class lookup did not resolve to CORPORATE (e.g. exposures
    # reclassified to COMMERCIAL_MORTGAGE by the real-estate splitter).
    cre_residual_rw = _cqs_table_lookup_expr(
        "cqs",
        CORPORATE_RISK_WEIGHTS,
        pl.lit(float(CORPORATE_RISK_WEIGHTS[CQS.UNRATED])),
    )
    return (
        # Commercial RE must precede residential — see _is_commercial_re_class.
        # CRR Art. 126: LTV + income cover.
        chain.when(_is_commercial_re_class(uc))
        .then(
            pl.when(pl.col("has_income_cover").fill_null(False))
            .then(
                _SA_CRR_RW["cre_rw_low"] * cre_secured_share + cre_residual_rw * cre_residual_share
            )
            .otherwise(pl.lit(_SA_CRR_RW["cre_rw_standard"]))
        )
        # CRR Art. 125 LTV split.
        .when(_is_residential_re_class(uc))
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
    )


def _crr_append_institution_maturity_branches(chain: _RWChain, uc: pl.Expr) -> ChainedThen:
    """Append CRR Art. 120/121 short-term institution branches."""
    is_institution = uc.str.contains("INSTITUTION", literal=True)
    is_rated = pl.col("cqs").is_not_null() & (pl.col("cqs") > 0)
    is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
    residual_mty = pl.col("residual_maturity_years").fill_null(1.0)
    original_mty = pl.col("original_maturity_years").fill_null(1.0)
    return (
        # Art. 120(2) Table 4: rated institution short-term (residual maturity
        # <= 3m). Also fires on derived ORIGINAL maturity when
        # residual_maturity_years is not populated upstream — original is
        # derived from (maturity_date - value_date) earlier in the SA pipeline,
        # mirroring the B31 ECRA short-term gate so date-only fixtures still
        # qualify for Table 4 preferential weights.
        chain.when(is_institution & is_rated & ((residual_mty <= 0.25) | (original_mty <= 0.25)))
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
# Risk-weight pipeline stages (module-private free functions).
#
# The public ``apply_risk_weights`` entry point composes these into a single
# chain. They are factored out here for readability — the full chain is long,
# and the dispatcher + framework override pattern matches the regulatory
# structure (CRR vs Basel 3.1).
# ---------------------------------------------------------------------------


@cites("PS1/26, paragraph 139")
@cites("PS1/26, paragraph 122")
def _prepare_risk_weight_lookup(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> tuple[pl.LazyFrame, pl.Expr, pl.Expr]:
    """Ensure required columns, classify for join, and attach CQS risk weights.

    Returns the exposures frame (with ``_lookup_class`` / ``_lookup_cqs`` /
    ``_upper_class`` / ``risk_weight`` columns added), the uppercase class
    expression reused by override chains, and the domestic-currency flag
    used for CGCB zero-weight treatment and sovereign-derived fallbacks.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # CQS-based risk weight table — Basel 3.1 uses revised corporate weights
    if resolved_pack.feature("sa_revised_risk_weight_tables"):
        rw_table = get_b31_combined_cqs_risk_weights().lazy()
    else:
        rw_table = get_combined_cqs_risk_weights().lazy()

    # Fill missing optional columns (counterparty attrs, CRM outputs,
    # classifier flags, defensive input-schema fallbacks) from the
    # declarative contract.
    exposures = ensure_columns(exposures, SA_INPUT_CONTRACT)

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

    # CRR Art. 114(4)/(7): Domestic CGCB exposures -> 0% RW. Must compare
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

    # CRR Art. 117(1) / PRA PS1/26 Art. 117(1)(a): non-named MDBs are treated
    # as institutions, so their primary CQS source is ``cp_institution_cqs``
    # (the MDB's own ECAI rating expressed as a CQS). When the exposure has
    # no top-level ``cqs`` (no rating attached at the rating-mapping stage)
    # but the counterparty carries an ``institution_cqs``, lift it into
    # ``cqs`` here so the downstream CQS-keyed branches and joins see it.
    # Named MDBs (mdb_named) bypass CQS entirely later — coalescing here is
    # harmless for them.
    is_mdb_class = upper == "MDB"
    # CRR Art. 107(2)(a): a non-qualifying CCP counterparty (entity_type "ccp"
    # demoted past the Art. 306(1) 2%/4% pin by cp_is_qccp=False) is treated as
    # an ordinary institution. Its own ECAI rating is carried on the synthetic
    # CCR row as ``cp_institution_cqs`` (the CCR adapter surfaces no top-level
    # ``cqs``), so lift it into ``cqs`` here — mirroring the MDB treatment —
    # so the Art. 120(1) Table 3 institution ladder resolves (e.g. CQS 2 -> 50%)
    # instead of the unrated 100% fallback. Scoped to ``ccp`` entity_type with a
    # null ``cqs`` so rated institutions and lending rows are untouched.
    is_non_qccp_institution = (pl.col("cp_entity_type").fill_null("") == "ccp") & ~pl.col(
        "cp_is_qccp"
    ).fill_null(True)
    exposures = exposures.with_columns(
        pl.when((is_mdb_class | is_non_qccp_institution) & pl.col("cqs").is_null())
        .then(pl.col("cp_institution_cqs"))
        .otherwise(pl.col("cqs"))
        .alias("cqs")
    )

    # PRA PS1/26 Art. 139(2B): for the purposes of Art. 122B(1) (the SA
    # specialised-lending routing), inferred / issuer-level (non-issue-specific)
    # ECAI assessments are disapplied. An SL exposure whose only resolved
    # external rating is not issue-specific must be treated as unrated, so we
    # null its CQS here. This re-routes it through the unrated SL override
    # (``b31_sa_sl_rw_expr``) instead of the rated-corporate CQS table. Scoped
    # to Basel 3.1 SL exposures only — ordinary rated corporates (Art. 122(2))
    # are untouched.
    if resolved_pack.feature("sa_sl_inferred_rating_disapplied"):
        is_sl_exposure = pl.col("sl_type").fill_null("").str.len_chars() > 0
        rating_not_issue_specific = (
            pl.col("external_rating_is_issue_specific").fill_null(True) == False  # noqa: E712
        )
        exposures = exposures.with_columns(
            pl.when(is_sl_exposure & rating_not_issue_specific)
            .then(pl.lit(None, dtype=pl.Int8))
            .otherwise(pl.col("cqs"))
            .alias("cqs")
        )

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


@cites("CRR Art. 134")
@cites("CRR Art. 137")
def _apply_b31_risk_weight_overrides(
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
        # Art. 137(1)-(2) Table 9: nominated ECA / MEIP score → direct sovereign
        # RW when no ECAI rating is present. Takes precedence over the Art. 114
        # unrated 100% fallback but not over the Art. 114(4)/(7) domestic 0%.
        # Identical to the CRR arm — MEIP risk weights are unchanged under PS1/26.
        .when(
            uc.str.contains("CENTRAL_GOVT", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
            & pl.col("cp_eca_score").is_not_null()
        )
        .then(_eca_meip_rw_expr())
        # QCCP trade exposures (CRR Art. 306, CRE54.14-15). The 2%/4% pin is
        # for QUALIFYING CCPs only (Art. 272 Def (88)): an explicit
        # cp_is_qccp=False demotes a ``ccp`` entity_type to the standard
        # institution ladder (Art. 107(2)(a)). An absent flag is treated as
        # qualifying so legacy ``ccp`` rows keep the prescribed weight.
        .when((pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(True))
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
        # PSE unrated: sovereign-derived RW lookup (Art. 116(1), Table 2).
        # Maps cp_sovereign_cqs -> RW; falls back to 100% when sovereign
        # CQS is unknown.
        .when((uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(
            _sovereign_derived_rw_expr(
                PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED,
                _SA_SHARED_RW["pse_unrated"],
            )
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
        # RGLA unrated non-domestic: sovereign-derived (Art. 115(1)(a)
        # Table 1A). Maps cp_sovereign_cqs -> RW; falls back to 100% when
        # sovereign CQS is unknown.
        .when((uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(
            _sovereign_derived_rw_expr(
                RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED,
                _SA_SHARED_RW["rgla_unrated"],
            )
        )
        # International Organisation -> 0% (Art. 118).
        .when(uc == "INTERNATIONAL_ORGANISATION")
        .then(pl.lit(_SA_SHARED_RW["io"]))
        # Named MDB -> 0% (Art. 117(2)).
        .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
        .then(pl.lit(_SA_SHARED_RW["mdb_named"]))
        # Unrated non-named MDB -> 50% (Art. 117(1), Table 2B).
        .when((uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(pl.lit(_SA_SHARED_RW["mdb_unrated"]))
    )

    chain = _b31_append_institution_maturity_branches(chain, uc)
    chain = _b31_append_corporate_maturity_branches(chain, uc)
    chain = _b31_append_high_risk_branch(chain, uc)

    # Corporate / retail / misc tail of the chain.
    is_unrated_corporate = (
        uc.str.contains("CORPORATE", literal=True)
        & ~uc.str.contains("SME", literal=True)
        & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
    )
    chain = (
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
        # Corporate SME: 85% — unrated only (Art. 122(11)). A rated SME
        # (CQS 1-6) keeps its Art. 122(2) Table-6 weight from the rw_table join.
        .when(
            uc.str.contains("CORPORATE", literal=True)
            & uc.str.contains("SME", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
        )
        .then(pl.lit(_SA_B31_RW["corporate_sme"]))
    )

    # Retail-class branches (Art. 123).
    chain = _b31_append_retail_branches(chain, uc)

    exposures = exposures.with_columns(
        chain
        # Unrated covered bonds: derive from issuer institution RW
        # (Art. 129(5)). ECRA (rated issuer, cp_institution_cqs) checked
        # first, then SCRA (unrated issuer, cp_scra_grade) as fallback.
        .when(
            uc.str.contains("COVERED_BOND", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
        )
        .then(_b31_unrated_cb_rw_expr())
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
        .when((uc == "OTHER") & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease"))
        .then(pl.lit(1.0) / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0))
        .when(uc == "OTHER")
        .then(pl.lit(_SA_SHARED_RW["other_default"]))
        # Equity (Art. 133(3)): 250% — full equity treatment (CIU,
        # transitional floor) lives in the dedicated equity table.
        .when(uc == "EQUITY")
        .then(pl.lit(_SA_B31_RW["equity"]))
        .otherwise(pl.col("risk_weight").fill_null(1.0))
        .alias("risk_weight")
    )
    return exposures


@cites("CRR Art. 134")
@cites("CRR Art. 137")
def _apply_crr_risk_weight_overrides(
    exposures: pl.LazyFrame,
    uc: pl.Expr,
    is_domestic_currency: pl.Expr,
) -> pl.LazyFrame:
    """Apply CRR class-specific risk-weight overrides (Art. 112-134)."""
    chain = (
        # Art. 114(4)/(7): Domestic CGCB -> 0% RW (overrides all CQS).
        pl.when(uc.str.contains("CENTRAL_GOVT", literal=True) & is_domestic_currency)
        .then(pl.lit(0.0))
        # Art. 137(1)-(2) Table 9: nominated ECA / MEIP score → direct sovereign
        # RW when no ECAI rating is present. Takes precedence over the Art. 114
        # unrated 100% fallback but not over the Art. 114(4)/(7) domestic 0%.
        .when(
            uc.str.contains("CENTRAL_GOVT", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
            & pl.col("cp_eca_score").is_not_null()
        )
        .then(_eca_meip_rw_expr())
        # QCCP trade exposures (CRR Art. 306, CRE54.14-15). The 2%/4% pin is
        # for QUALIFYING CCPs only (Art. 272 Def (88)): an explicit
        # cp_is_qccp=False demotes a ``ccp`` entity_type to the standard
        # institution ladder (Art. 107(2)(a)). An absent flag is treated as
        # qualifying so legacy ``ccp`` rows keep the prescribed weight.
        .when((pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(True))
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
        # Corporate SME: 100% — unrated only (Art. 122). A rated SME (CQS 1-6)
        # keeps its Art. 122 CQS-table weight from the rw_table join; SME relief
        # is delivered separately via the Art. 501 supporting factor.
        .when(
            uc.str.contains("CORPORATE", literal=True)
            & uc.str.contains("SME", literal=True)
            & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0))
        )
        .then(pl.lit(_SA_CRR_RW["corporate_sme"]))
    )

    # Retail-class branches (Art. 123).
    chain = _crr_append_retail_branches(chain, uc)

    # Sovereign-like (PSE, RGLA, MDB, IO).
    chain = (
        # PSE short-term (Art. 116(3)): original maturity <= 3m -> 20%.
        chain.when(
            (uc == "PSE")
            & pl.col("original_maturity_years").is_not_null()
            & (pl.col("original_maturity_years") <= 0.25)
        )
        .then(pl.lit(_SA_SHARED_RW["pse_short_term"]))
        # PSE unrated: sovereign-derived RW lookup (Art. 116(1), Table 2).
        # Maps cp_sovereign_cqs -> RW; falls back to 100% when sovereign
        # CQS is unknown.
        .when((uc == "PSE") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(
            _sovereign_derived_rw_expr(
                PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED,
                _SA_SHARED_RW["pse_unrated"],
            )
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
        # RGLA unrated non-domestic: sovereign-derived (Art. 115(1)(a)
        # Table 1A). Maps cp_sovereign_cqs -> RW; falls back to 100% when
        # sovereign CQS is unknown.
        .when((uc == "RGLA") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(
            _sovereign_derived_rw_expr(
                RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED,
                _SA_SHARED_RW["rgla_unrated"],
            )
        )
        # International Organisation -> 0% (Art. 118).
        .when(uc == "INTERNATIONAL_ORGANISATION")
        .then(pl.lit(_SA_SHARED_RW["io"]))
        # Named MDB -> 0% (Art. 117(2)).
        .when((uc == "MDB") & (pl.col("cp_entity_type").fill_null("") == "mdb_named"))
        .then(pl.lit(_SA_SHARED_RW["mdb_named"]))
        # CRR Art. 117(1): non-named MDBs are treated as institutions and use
        # the institution risk weight tables (Art. 120 Table 3 if rated, Art.
        # 121 Table 5 sovereign-derived if unrated). The dedicated Basel 3.1
        # Table 2B path (PRA PS1/26 Art. 117(1)(a)) does NOT apply under CRR.
        # The Art. 119(2)/120(2)/121(3) short-term carve-outs are excluded for
        # MDBs by Art. 117(1), so no short-term branch is consulted here.
        # Rated non-named MDB: Art. 120 Table 3 (institution own CQS).
        .when((uc == "MDB") & pl.col("cqs").is_not_null() & (pl.col("cqs") > 0))
        .then(build_institution_guarantor_rw_expr("cqs", is_basel_3_1=False))
        # Unrated non-named MDB: Art. 121 Table 5 sovereign-derived; Art. 121
        # fallback (100%) when the MDB's home sovereign CQS is unknown.
        .when((uc == "MDB") & (pl.col("cqs").is_null() | (pl.col("cqs") <= 0)))
        .then(
            _sovereign_derived_rw_expr(
                INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED,
                float(INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]),
            )
        )
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
        # CRR Art. 128 (high-risk items, 150%) was OMITTED from UK onshored CRR
        # by SI 2021/1078 reg. 6(3)(a) with effect from 1 January 2022. Exposures
        # that map to HIGH_RISK under the entity-type table therefore fall through
        # to the OTHER (residual) class at 100% under UK CRR. The 150% treatment
        # is re-introduced under PRA PS1/26 Basel 3.1 — see
        # _apply_b31_risk_weight_overrides.
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
        .when((uc == "OTHER") & (pl.col("cp_entity_type").fill_null("") == "other_residual_lease"))
        .then(pl.lit(1.0) / pl.col("residual_maturity_years").fill_null(1.0).clip(lower_bound=1.0))
        .when(uc == "OTHER")
        .then(pl.lit(_SA_SHARED_RW["other_default"]))
        # Equity (Art. 133(2)): flat 100%.
        .when(uc == "EQUITY")
        .then(pl.lit(_SA_CRR_RW["equity"]))
        .otherwise(pl.col("risk_weight").fill_null(1.0))
        .alias("risk_weight")
    )
    return exposures


def _apply_sovereign_floor_for_institutions(
    exposures: pl.LazyFrame,
    is_domestic_currency_expr: pl.Expr,
) -> pl.LazyFrame:
    """Apply sovereign RW floor for FX unrated institution exposures.

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

    # Sovereign CQS → risk weight mapping (Art. 114 table —
    # CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS). Unknown CQS → null so the
    # downstream floor predicate (`_floor_applies` requires _sovereign_rw
    # to be non-null) leaves the exposure unchanged.
    _sovereign_rw = _cqs_table_lookup_expr(
        "cp_sovereign_cqs",
        CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
        pl.lit(None).cast(pl.Float64),
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


@cites("CRR Art. 127")
@cites("PS1/26, paragraph 127")
def _apply_defaulted_risk_weight(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply Art. 127 defaulted risk weight to the full post-CRM exposure.

    PS1/26 Art. 127(1)-(2) assign 100% or 150% to the part of a defaulted
    exposure that is not secured by recognised collateral or covered by
    recognised unfunded credit protection, where the unsecured part is
    determined by the CRM method the institution applies (Art. 191A(2)).

    Under the Financial Collateral Comprehensive Method (the default for
    SA), eligible financial collateral has already reduced ``ead_final``
    in the CRM stage and eligible residential/commercial real estate has
    been routed via class reclassification — so ``ead_final`` already
    represents the unsecured value and Art. 127(1) applies to it flat.
    FCSM (Simple Method) is handled downstream by
    ``apply_fcsm_rw_substitution``, which blends the defaulted RW with
    the collateral RW per the substitution rule.

    Basel 3.1 Art. 127(3) / CRE20.88 exception: a residential RE default
    that is not materially dependent on cash-flows of the property is
    assigned 100% flat, regardless of provisions.

    References:
    - PS1/26 Art. 127(1): unsecured part 100%/150% by provision coverage
    - PS1/26 Art. 127(2): unsecured part determined by the CRM method
    - PS1/26 Art. 127(3) / CRE20.88: RESI RE non-income flat 100%
    - CRR Art. 127(1)-(2): CRR predecessor (pre-provision denominator)
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    _uc = pl.col("exposure_class").fill_null("").str.to_uppercase()
    ead = pl.col("ead_final")

    if resolved_pack.feature("sa_revised_defaulted_treatment"):
        # B31 RESI RE non-income-dependent: 100% flat (Art. 127(3) / CRE20.88).
        is_resi_re_non_income = (
            _is_residential_re_class(_uc)
            & ~_is_commercial_re_class(_uc)
            & ~pl.col("has_income_cover").fill_null(False)
        )

        # PS1/26 Art. 127(1): denominator is "the outstanding amount of the
        # item or facility" — gross outstanding (pre-CRM, pre-provision).
        # Reconstruct from ead_gross (post-CCF, post-provision, pre-CRM) plus
        # provision_deducted.
        gross_outstanding = pl.col("ead_gross") + pl.col("provision_deducted")
        provision_rw = (
            pl.when(
                pl.col("provision_allocated")
                >= _SA_B31_RW["defaulted_threshold"] * gross_outstanding
            )
            .then(pl.lit(_SA_B31_RW["defaulted_high"]))
            .otherwise(pl.lit(_SA_B31_RW["defaulted_low"]))
        )

        defaulted_rw = (
            pl.when(is_resi_re_non_income)
            .then(pl.lit(_SA_B31_RW["defaulted_resi_re_non_income"]))
            .otherwise(provision_rw)
        )
    else:
        # CRR Art. 127(1): denominator is the pre-provision exposure value
        # (ead_final is post-provision, so add provision_deducted back).
        unsecured_pre_prov = ead + pl.col("provision_deducted")
        defaulted_rw = (
            pl.when(
                pl.col("provision_allocated")
                >= _SA_CRR_RW["defaulted_threshold"] * unsecured_pre_prov
            )
            .then(pl.lit(_SA_CRR_RW["defaulted_high"]))
            .otherwise(pl.lit(_SA_CRR_RW["defaulted_low"]))
        )

    # Art. 128 (HIGH_RISK) takes precedence per Table A2 priority 4 > 5
    is_defaulted = pl.col("is_defaulted").fill_null(False) & (_uc != "HIGH_RISK")

    return exposures.with_columns(
        pl.when(is_defaulted)
        .then(defaulted_rw)
        .otherwise(pl.col("risk_weight"))
        .alias("risk_weight")
    )
