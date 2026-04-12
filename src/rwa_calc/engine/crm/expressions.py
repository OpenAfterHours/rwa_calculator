"""
Polars expression builders for CRM collateral and beneficiary classification.

Holds the Polars expression builders used across the CRM pipeline to
classify collateral into regulatory categories, derive supervisory LGD,
overcollateralisation ratios, and minimum collateralisation thresholds
per row, plus the waterfall ordering (WATERFALL_ORDER) and allocation
column naming (CRM_ALLOC_COLUMNS) that drive the Art. 231 sequential
fill in collateral.py.

Sibling modules providing the data this module consumes:
- data/schemas.py: input-domain collateral type-set lists and the
  canonical collateral_type -> category mapping
- data/tables/crm_supervisory.py: regulatory values (supervisory LGD,
  overcollateralisation ratios, minimum thresholds, zero-haircut
  sovereign CQS cap)

References:
    CRR Art. 161, 224, 230, 231: Supervisory LGD, haircuts,
        overcollateralisation, waterfall
    CRE22.52-53, CRE32.9-12: Basel 3.1 equivalents
"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.schemas import (
    COVERED_BOND_COLLATERAL_TYPES,
    DIRECT_BENEFICIARY_TYPES,
    FINANCIAL_COLLATERAL_TYPES,
    LIFE_INSURANCE_COLLATERAL_TYPES,
    OTHER_PHYSICAL_COLLATERAL_TYPES,
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
)
from rwa_calc.data.tables.crm_supervisory import (
    BASEL31_SUPERVISORY_LGD,
    CRR_SUPERVISORY_LGD,
    MIN_COLLATERALISATION_THRESHOLDS,
    OVERCOLLATERALISATION_RATIOS,
)

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
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit(lgd["life_insurance"]))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit(lgd["financial"]))
        .when(ct.is_in(COVERED_BOND_COLLATERAL_TYPES))
        .then(pl.lit(lgd["covered_bond"]))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit(lgd["receivables"]))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit(lgd["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
        .then(pl.lit(lgd["other_physical"]))
        .otherwise(pl.lit(lgd["unsecured"]))
    )


def overcollateralisation_ratio_expr() -> pl.Expr:
    """Build expression mapping collateral_type to overcollateralisation ratio."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["life_insurance"]))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["financial"]))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["receivables"]))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
        .then(pl.lit(OVERCOLLATERALISATION_RATIOS["other_physical"]))
        .otherwise(pl.lit(1.0))
    )


def min_collateralisation_threshold_expr() -> pl.Expr:
    """Build expression mapping collateral_type to minimum collateralisation threshold."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["life_insurance"]))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["financial"]))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["receivables"]))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
        .then(pl.lit(MIN_COLLATERALISATION_THRESHOLDS["other_physical"]))
        .otherwise(pl.lit(0.0))
    )


def is_financial_collateral_type_expr() -> pl.Expr:
    """Build expression returning True for financial collateral types."""
    return _coll_type_lower().is_in(FINANCIAL_COLLATERAL_TYPES)


def collateral_category_expr() -> pl.Expr:
    """Build expression classifying collateral into COREP categories (C 08.01 cols 0170-0210)."""
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit("life_insurance"))
        .when(ct.is_in(["cash", "deposit"]))
        .then(pl.lit("cash"))
        .when(ct.is_in(COVERED_BOND_COLLATERAL_TYPES))
        .then(pl.lit("covered_bond"))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit("financial"))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit("receivables"))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit("real_estate"))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
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
