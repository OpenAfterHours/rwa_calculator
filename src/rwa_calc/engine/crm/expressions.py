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
- rulebook/packs/{common,b31}.py: regulatory values (supervisory LGD,
  overcollateralisation ratios, minimum collateralisation thresholds,
  zero-haircut sovereign CQS cap) carrying citations, read per-run via
  rulebook.resolve

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


def supervisory_lgd_values(pack: ResolvedRulepack) -> dict[str, float]:
    """Project the canonical ``firb_supervisory_lgd`` table to CRM simple categories.

    Reproduces the CRM-shape LGD dict (financial / receivables / real_estate /
    other_physical / unsecured / covered_bond / life_insurance, plus
    ``unsecured_fse`` under Basel 3.1 and the CRR Art. 230 Table 5
    ``*_subordinated`` secured-portion LGDS) from the single FIRB-granularity
    DecisionTable — one source of truth across the CRM and IRB-direct shapes.
    """
    rows = {keys: float(value) for keys, value in pack.decision("firb_supervisory_lgd").rows}
    values = {
        "financial": rows[("financial_collateral", "senior", False)],
        "receivables": rows[("receivables", "senior", False)],
        "real_estate": rows[("residential_re", "senior", False)],
        "other_physical": rows[("other_physical", "senior", False)],
        "unsecured": rows[("unsecured", "senior", False)],
        "covered_bond": rows[("covered_bond", "senior", False)],
        "life_insurance": rows[("life_insurance", "senior", False)],
    }
    # FSE senior unsecured exists only where the regime splits FSE (Basel 3.1).
    unsecured_fse = rows.get(("unsecured", "senior", True))
    if unsecured_fse is not None and unsecured_fse != values["unsecured"]:
        values["unsecured_fse"] = unsecured_fse
    # CRR Art. 230 Table 5 subordinated secured-portion LGDS (dropped under B31).
    for crm_key, ct in (
        ("receivables_subordinated", "receivables"),
        ("real_estate_subordinated", "residential_re"),
        ("other_physical_subordinated", "other_physical"),
    ):
        sub = rows.get((ct, "subordinated", False))
        if sub is not None:
            values[crm_key] = sub
    return values


def subordinated_unsecured_lgd(pack: ResolvedRulepack) -> float:
    """The F-IRB subordinated unsecured supervisory LGD (Art. 161(1)(b), 75%).

    Sourced from the canonical ``firb_supervisory_lgd`` table's
    ``(unsecured, subordinated, …)`` row; regime-invariant (75% under both CRR
    and Basel 3.1). Replaces the historical hardcoded ``pl.lit(0.75)``
    subordinated literals in the collateral / no-collateral LGD waterfall.
    """
    rows = {keys: float(value) for keys, value in pack.decision("firb_supervisory_lgd").rows}
    return rows[("unsecured", "subordinated", False)]


@cites("CRR Art. 223(4)")
@cites("PS1/26 Art. 230(1)")
def lgd_star_exposure_basis_expr(*, has_volatility_haircut: bool = True) -> pl.Expr:
    """The Art. 230(1) exposure basis E' = E x (1 + HE) that LGD* divides by.

    ``E`` is ``ead_for_crm``, the CCF=100% exposure value (CRR Art. 223(4) /
    PS1/26 Art. 223(4)) — NOT the post-CCF ``ead_gross``: an off-balance-sheet
    item enters credit risk mitigation at 100% of nominal, so the collateral
    shares that weight the LGD* blend are shares of the pre-CCF basis. ``HE``
    is the exposure's own volatility haircut (Art. 223(5)), non-zero only where
    the row lends out a debt security, so E' == E on every other row.

    The single home for this quantity: the F-IRB / A-IRB LGD* formula and the
    Art. 161(5)(b) / 164(4)(c) A-IRB LGD *input floor* blend must divide by the
    same basis (``engine/crm/collateral.py``, ``engine/irb/formulas.py``).

    Args:
        has_volatility_haircut: False where the caller's frame predates the
            ``exposure_volatility_haircut`` column (pre-seal CRM inputs built
            by direct unit-test callers), which is equivalent to HE = 0.
    """
    if not has_volatility_haircut:
        return pl.col("ead_for_crm")
    he_factor = pl.lit(1.0) + pl.col("exposure_volatility_haircut").fill_null(0.0)
    return pl.col("ead_for_crm") * he_factor


def collateral_lgd_expr(pack: ResolvedRulepack) -> pl.Expr:
    """Build expression mapping collateral_type to supervisory LGD.

    Note: The "otherwise" (unsecured) value uses the non-FSE LGD under Basel 3.1.
    FSE-specific unsecured LGD (45%) is handled at the exposure level in
    collateral.py, not here — this expression is for per-collateral-type LGDS.
    """
    lgd = supervisory_lgd_values(pack)
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
