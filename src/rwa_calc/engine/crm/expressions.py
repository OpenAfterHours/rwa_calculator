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

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import (
    COVERED_BOND_COLLATERAL_TYPES,
    FINANCIAL_COLLATERAL_TYPES,
    LIFE_INSURANCE_COLLATERAL_TYPES,
    OTHER_PHYSICAL_COLLATERAL_TYPES,
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
)
from rwa_calc.data.tables.crm_supervisory import (
    BASEL31_SUPERVISORY_LGD,
    CRR_SUPERVISORY_LGD,
)
from rwa_calc.engine.kernels.allocation import (
    beneficiary_level_expr as kernel_beneficiary_level_expr,
)
from rwa_calc.rulebook.compile import lookup_float_map

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

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


@cites("PS1/26 Art. 230(1)")
def overcollateralisation_ratio_expr(pack: ResolvedRulepack) -> pl.Expr:
    """Build expression mapping collateral_type to overcollateralisation ratio.

    CRR Art. 230 (Table 5) requires explicit overcollateralisation divisors for
    non-financial collateral (RE/other physical 1.4x, receivables 1.25x).

    PS1/26 Art. 230(1) replaces the CRR step-function with a continuous LGD*
    formula in which the haircut HC is applied multiplicatively at the haircut
    stage; no overcollateralisation divisor is applied for non-financial
    collateral under Basel 3.1. Whether the divisor applies is the regime
    Feature ``firb_overcollateralisation_divisor_applies``; the ratios
    themselves are the regime-invariant ``overcollateralisation_ratios`` lookup.
    """
    if not pack.feature("firb_overcollateralisation_divisor_applies"):
        # PS1/26 Art. 230(1): FCM HC is applied multiplicatively, no
        # overcollateralisation divisor — the ratio is 1.0 for every type.
        return pl.lit(1.0)
    ratios = lookup_float_map(pack.lookup("overcollateralisation_ratios"))
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit(ratios["life_insurance"]))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit(ratios["financial"]))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit(ratios["receivables"]))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit(ratios["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
        .then(pl.lit(ratios["other_physical"]))
        .otherwise(pl.lit(1.0))
    )


def min_collateralisation_threshold_expr(pack: ResolvedRulepack) -> pl.Expr:
    """Build expression mapping collateral_type to minimum collateralisation threshold.

    Values are the regime-invariant ``min_collateralisation_thresholds`` lookup
    (CRR Art. 230). Whether the 30% C*/C** gate is *applied* is the regime
    Feature ``firb_min_collateralisation_threshold_applies``, checked by the
    caller in ``collateral.py`` (Basel 3.1 skips the gate per PS1/26 Art. 230(1)).
    """
    thresholds = lookup_float_map(pack.lookup("min_collateralisation_thresholds"))
    ct = _coll_type_lower()
    return (
        pl.when(ct.is_in(LIFE_INSURANCE_COLLATERAL_TYPES))
        .then(pl.lit(thresholds["life_insurance"]))
        .when(ct.is_in(FINANCIAL_COLLATERAL_TYPES))
        .then(pl.lit(thresholds["financial"]))
        .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
        .then(pl.lit(thresholds["receivables"]))
        .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
        .then(pl.lit(thresholds["real_estate"]))
        .when(ct.is_in(OTHER_PHYSICAL_COLLATERAL_TYPES))
        .then(pl.lit(thresholds["other_physical"]))
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
    """Build expression classifying beneficiary_type into direct/facility/counterparty.

    Thin alias of the allocation kernel's classifier with the collateral-copy
    fallback (null / unknown beneficiary types -> direct).
    """
    return kernel_beneficiary_level_expr(bt_col, unknown="direct")
