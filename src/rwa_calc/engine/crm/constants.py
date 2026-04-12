"""
Shared collateral type classifications and Polars expression builders for CRM.

Holds input-domain string lists for collateral classification and the
expression builders that consume them. Regulatory values (supervisory
LGD, overcollateralisation ratios, minimum thresholds, zero-haircut
sovereign CQS cap) live in data/tables/crm_supervisory.py and are
imported here for use by the expression builders below.

References:
    CRR Art. 161, 224, 230: Supervisory LGD, haircuts, overcollateralisation
    CRE22.52-53, CRE32.9-12: Basel 3.1 equivalents
"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.tables.crm_supervisory import (
    BASEL31_SUPERVISORY_LGD,
    CRR_SUPERVISORY_LGD,
    MIN_COLLATERALISATION_THRESHOLDS,
    OVERCOLLATERALISATION_RATIOS,
)

# ---------------------------------------------------------------------------
# Collateral type classifications
# ---------------------------------------------------------------------------

FINANCIAL_TYPES: list[str] = [
    "cash",
    "deposit",
    "gold",
    "financial_collateral",
    "government_bond",
    "corporate_bond",
    "equity",
    "credit_linked_note",
]

RECEIVABLE_TYPES: list[str] = ["receivables", "trade_receivables"]

REAL_ESTATE_TYPES: list[str] = [
    "real_estate",
    "property",
    "rre",
    "cre",
    "residential_re",
    "commercial_re",
    "residential",
    "commercial",
    "residential_property",
    "commercial_property",
]

OTHER_PHYSICAL_TYPES: list[str] = ["other_physical", "equipment", "inventory", "other"]

COVERED_BOND_TYPES: list[str] = ["covered_bond", "covered_bonds"]

LIFE_INSURANCE_TYPES: list[str] = ["life_insurance"]

CREDIT_LINKED_NOTE_TYPES: list[str] = ["credit_linked_note"]

# Art. 227(2)(a): collateral types eligible for zero-haircut treatment in repos.
# Both the exposure and collateral must be cash or 0%-RW sovereign debt securities.
ZERO_HAIRCUT_ELIGIBLE_TYPES: list[str] = [
    "cash",
    "deposit",
    "govt_bond",
    "sovereign_bond",
    "government_bond",
    "gilt",
]

# Subset of real estate types that are NOT eligible financial collateral
# (used for SA EAD reduction eligibility check)
NON_ELIGIBLE_RE_TYPES: list[str] = [
    "real_estate",
    "property",
    "rre",
    "cre",
    "residential_property",
    "commercial_property",
]

# ---------------------------------------------------------------------------
# Beneficiary type classifications
# ---------------------------------------------------------------------------

DIRECT_BENEFICIARY_TYPES: list[str] = ["exposure", "loan", "contingent"]

# ---------------------------------------------------------------------------
# Polars expression builders
# ---------------------------------------------------------------------------


def _coll_type_lower() -> pl.Expr:
    """Lowercase collateral_type expression."""
    return pl.col("collateral_type").str.to_lowercase()


def supervisory_lgd_values(is_basel_3_1: bool) -> dict[str, float]:
    """Return the appropriate supervisory LGD dict for the framework."""
    return BASEL31_SUPERVISORY_LGD if is_basel_3_1 else CRR_SUPERVISORY_LGD


def collateral_lgd_expr(is_basel_3_1: bool) -> pl.Expr:
    """Build expression mapping collateral_type to supervisory LGD.

    Note: The "otherwise" (unsecured) value uses the non-FSE LGD under Basel 3.1.
    FSE-specific unsecured LGD (45%) is handled at the exposure level in
    collateral.py, not here — this expression is for per-collateral-type LGDS.
    """
    lgd = supervisory_lgd_values(is_basel_3_1)
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_TYPES))
        .then(pl.lit(lgd["life_insurance"]))
        .when(ct.is_in(FINANCIAL_TYPES))
        .then(pl.lit(lgd["financial"]))
        .when(ct.is_in(COVERED_BOND_TYPES))
        .then(pl.lit(lgd["covered_bond"]))
        .when(ct.is_in(RECEIVABLE_TYPES))
        .then(pl.lit(lgd["receivables"]))
        .when(ct.is_in(REAL_ESTATE_TYPES))
        .then(pl.lit(lgd["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_TYPES))
        .then(pl.lit(lgd["other_physical"]))
        .otherwise(pl.lit(lgd["unsecured"]))
    )


def overcollateralisation_ratio_expr() -> pl.Expr:
    """Build expression mapping collateral_type to overcollateralisation ratio."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["life_insurance"]))
        .when(ct.is_in(FINANCIAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["financial"]))
        .when(ct.is_in(RECEIVABLE_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["receivables"]))
        .when(ct.is_in(REAL_ESTATE_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["other_physical"]))
        .otherwise(pl.lit(1.0))
    )


def min_collateralisation_threshold_expr() -> pl.Expr:
    """Build expression mapping collateral_type to minimum collateralisation threshold."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["life_insurance"]))
        .when(ct.is_in(FINANCIAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["financial"]))
        .when(ct.is_in(RECEIVABLE_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["receivables"]))
        .when(ct.is_in(REAL_ESTATE_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["other_physical"]))
        .otherwise(pl.lit(0.0))
    )


def is_financial_collateral_type_expr() -> pl.Expr:
    """Build expression returning True for financial collateral types."""
    return _coll_type_lower().is_in(FINANCIAL_TYPES)


def collateral_category_expr() -> pl.Expr:
    """Build expression classifying collateral into COREP categories (C 08.01 cols 0170-0210)."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_TYPES))
        .then(pl.lit("life_insurance"))
        .when(ct.is_in(["cash", "deposit"]))
        .then(pl.lit("cash"))
        .when(ct.is_in(COVERED_BOND_TYPES))
        .then(pl.lit("covered_bond"))
        .when(ct.is_in(FINANCIAL_TYPES))
        .then(pl.lit("financial"))
        .when(ct.is_in(RECEIVABLE_TYPES))
        .then(pl.lit("receivables"))
        .when(ct.is_in(REAL_ESTATE_TYPES))
        .then(pl.lit("real_estate"))
        .when(ct.is_in(OTHER_PHYSICAL_TYPES))
        .then(pl.lit("other_physical"))
        .otherwise(pl.lit("other"))
    )


# Waterfall ordering for Art. 231 sequential fill (lowest LGDS first).
# Each tuple: (category_filter_values, lgds_key, aggregate_suffix)
WATERFALL_ORDER: list[tuple[list[str], str, str]] = [
    (["cash", "financial"], "financial", "fin"),
    (["covered_bond"], "covered_bond", "cb"),
    (["receivables"], "receivables", "rec"),
    (["real_estate"], "real_estate", "re"),
    (["other_physical", "other"], "other_physical", "op"),
    (
        ["life_insurance"],
        "life_insurance",
        "li",
    ),  # Art. 232: LGDS = 40% (same as other_physical/CRR)
]

# Per-type allocation column names preserved from the Art. 231 waterfall.
# These encode the dollar amount of EAD absorbed by each collateral category
# in sequential fill order. Used by the A-IRB blended LGD floor (Art. 164(4)(c)).
CRM_ALLOC_COLUMNS: dict[str, str] = {
    "fin": "crm_alloc_financial",
    "cb": "crm_alloc_covered_bond",
    "rec": "crm_alloc_receivables",
    "re": "crm_alloc_real_estate",
    "op": "crm_alloc_other_physical",
    "li": "crm_alloc_life_insurance",
}


def beneficiary_level_expr(bt_col: str = "beneficiary_type") -> pl.Expr:
    """Build expression classifying beneficiary_type into direct/facility/counterparty."""
    bt_lower = pl.col(bt_col).str.to_lowercase()
    return (
        pl.when(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))
        .then(pl.lit("direct"))
        .when(bt_lower == "facility")
        .then(pl.lit("facility"))
        .when(bt_lower == "counterparty")
        .then(pl.lit("counterparty"))
        .otherwise(pl.lit("direct"))
    )
