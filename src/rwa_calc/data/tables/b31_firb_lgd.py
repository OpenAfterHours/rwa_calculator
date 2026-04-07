"""
Basel 3.1 F-IRB Supervisory LGD values (PRA PS1/26 Art. 161).

Pipeline position:
    Data Tables -> CRM Processor -> IRB Calculator

Key responsibilities:
- Basel 3.1 F-IRB supervisory LGD DataFrame for efficient joins
- FSE vs non-FSE senior unsecured distinction (45% vs 40%)
- Covered bond LGD (11.25%, Art. 161(1B))
- Reduced LGDS values for non-financial collateral (CRE32.9-12)

References:
- PRA PS1/26 Art. 161(1): Supervisory LGD values
- PRA PS1/26 Art. 161(1B): Covered bond LGD
- CRE32.9-12: Basel 3.1 collateral LGDS values
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from .crr_firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_MIN_COLLATERALISATION_THRESHOLDS,
    FIRB_OVERCOLLATERALISATION_RATIOS,
)

# =============================================================================
# BASEL 3.1 F-IRB SUPERVISORY LGD CONSTANTS (PRA PS1/26 Art. 161)
# =============================================================================

# Key changes from CRR -> Basel 3.1:
# - Non-FSE senior unsecured: 45% -> 40% (Art. 161(1)(aa))
# - FSE senior unsecured: 45% unchanged (Art. 161(1)(a))
# - Covered bonds: new at 11.25% (Art. 161(1B))
# - Receivables LGDS: 35% -> 20% (CRE32.9)
# - Real estate LGDS: 35% -> 20% (CRE32.10-11)
# - Other physical LGDS: 40% -> 25% (CRE32.12)
# - Financial collateral: 0% unchanged
# - Subordinated: 75% unchanged

B31_FIRB_LGD_UNSECURED_SENIOR: Decimal = Decimal("0.40")
"""Non-FSE senior unsecured LGD under Basel 3.1 (Art. 161(1)(aa))."""

B31_FIRB_LGD_UNSECURED_SENIOR_FSE: Decimal = Decimal("0.45")
"""FSE senior unsecured LGD under Basel 3.1 (Art. 161(1)(a))."""

B31_FIRB_LGD_SUBORDINATED: Decimal = Decimal("0.75")
"""Subordinated LGD, unchanged from CRR (Art. 161(1)(b))."""

B31_FIRB_LGD_COVERED_BOND: Decimal = Decimal("0.1125")
"""Covered bond LGD (Art. 161(1B))."""

B31_FIRB_LGD_FINANCIAL_COLLATERAL: Decimal = Decimal("0.00")
"""Financial collateral LGD, unchanged from CRR."""

B31_FIRB_LGD_RECEIVABLES: Decimal = Decimal("0.20")
"""Receivables LGDS under Basel 3.1 (CRR: 35%, CRE32.9)."""

B31_FIRB_LGD_RESIDENTIAL_RE: Decimal = Decimal("0.20")
"""Residential RE LGDS under Basel 3.1 (CRR: 35%, CRE32.10)."""

B31_FIRB_LGD_COMMERCIAL_RE: Decimal = Decimal("0.20")
"""Commercial RE LGDS under Basel 3.1 (CRR: 35%, CRE32.11)."""

B31_FIRB_LGD_OTHER_PHYSICAL: Decimal = Decimal("0.25")
"""Other physical collateral LGDS under Basel 3.1 (CRR: 40%, CRE32.12)."""


# =============================================================================
# DATAFRAME GENERATOR
# =============================================================================


def _create_b31_firb_lgd_df() -> pl.DataFrame:
    """Create Basel 3.1 F-IRB supervisory LGD lookup DataFrame.

    Includes FSE/non-FSE distinction for unsecured exposures and all
    B31-revised collateral LGDS values. Overcollateralisation ratios
    are unchanged from CRR (Art. 230).

    Returns:
        DataFrame with columns: collateral_type, seniority, is_fse, lgd,
        overcollateralisation_ratio, min_threshold, description
    """
    rows = [
        # Unsecured — non-FSE (Art. 161(1)(aa))
        {
            "collateral_type": "unsecured",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_UNSECURED_SENIOR),
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Unsecured senior claims — non-FSE (Art. 161(1)(aa))",
        },
        # Unsecured — FSE (Art. 161(1)(a))
        {
            "collateral_type": "unsecured",
            "seniority": "senior",
            "is_fse": True,
            "lgd": float(B31_FIRB_LGD_UNSECURED_SENIOR_FSE),
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Unsecured senior claims — FSE (Art. 161(1)(a))",
        },
        # Subordinated — unchanged
        {
            "collateral_type": "unsecured",
            "seniority": "subordinated",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_SUBORDINATED),
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Subordinated claims (Art. 161(1)(b))",
        },
        # Covered bonds — Art. 161(1B)
        {
            "collateral_type": "covered_bond",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_COVERED_BOND),
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Covered bonds (Art. 161(1B))",
        },
        # Financial collateral — unchanged
        {
            "collateral_type": "financial_collateral",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_FINANCIAL_COLLATERAL),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["financial"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["financial"],
            "description": "Eligible financial collateral (after haircuts)",
        },
        {
            "collateral_type": "cash",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_FINANCIAL_COLLATERAL),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["financial"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["financial"],
            "description": "Cash collateral",
        },
        # Receivables — reduced (CRE32.9)
        {
            "collateral_type": "receivables",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_RECEIVABLES),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["receivables"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["receivables"],
            "description": "Secured by receivables (CRR: 35%)",
        },
        # Real estate — reduced (CRE32.10-11)
        {
            "collateral_type": "residential_re",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_RESIDENTIAL_RE),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["real_estate"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["real_estate"],
            "description": "Secured by residential RE (CRR: 35%)",
        },
        {
            "collateral_type": "commercial_re",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_COMMERCIAL_RE),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["real_estate"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["real_estate"],
            "description": "Secured by commercial RE (CRR: 35%)",
        },
        {
            "collateral_type": "real_estate",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_RESIDENTIAL_RE),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["real_estate"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["real_estate"],
            "description": "Secured by real estate — general (CRR: 35%)",
        },
        # Other physical — reduced (CRE32.12)
        {
            "collateral_type": "other_physical",
            "seniority": "senior",
            "is_fse": False,
            "lgd": float(B31_FIRB_LGD_OTHER_PHYSICAL),
            "overcollateralisation_ratio": FIRB_OVERCOLLATERALISATION_RATIOS["other_physical"],
            "min_threshold": FIRB_MIN_COLLATERALISATION_THRESHOLDS["other_physical"],
            "description": "Other eligible physical collateral (CRR: 40%)",
        },
    ]

    return pl.DataFrame(rows).with_columns(
        [
            pl.col("lgd").cast(pl.Float64),
            pl.col("overcollateralisation_ratio").cast(pl.Float64),
            pl.col("min_threshold").cast(pl.Float64),
        ]
    )


def get_b31_firb_lgd_table() -> pl.DataFrame:
    """Get Basel 3.1 F-IRB supervisory LGD lookup table.

    Returns:
        DataFrame with columns: collateral_type, seniority, is_fse, lgd,
        overcollateralisation_ratio, min_threshold, description
    """
    return _create_b31_firb_lgd_df()


def lookup_b31_firb_lgd(
    collateral_type: str | None = None,
    is_subordinated: bool = False,
    is_financial_sector_entity: bool = False,
) -> tuple[Decimal, str]:
    """Look up Basel 3.1 F-IRB supervisory LGD.

    Under Basel 3.1 (PRA PS1/26 Art. 161(1)), key differences from CRR:
    - Non-FSE senior unsecured: 40% (CRR: 45%)
    - FSE senior unsecured: 45% (unchanged)
    - Covered bonds: 11.25% (Art. 161(1B))
    - Receivables LGDS: 20% (CRR: 35%)
    - Real estate LGDS (RRE/CRE): 20% (CRR: 35%)
    - Other physical LGDS: 25% (CRR: 40%)

    Args:
        collateral_type: Type of collateral securing the exposure (None = unsecured)
        is_subordinated: Whether the exposure is subordinated
        is_financial_sector_entity: Whether the obligor is a financial sector entity
            (only affects unsecured LGD)

    Returns:
        Tuple of (supervisory_lgd, description)
    """
    table = BASEL31_FIRB_SUPERVISORY_LGD

    # Subordinated always gets 75% regardless of collateral
    if is_subordinated:
        return table["subordinated"], "Subordinated (75%)"

    # No collateral — senior unsecured (with FSE distinction)
    if collateral_type is None:
        if is_financial_sector_entity:
            return table["unsecured_senior_fse"], "Unsecured senior FSE (45%)"
        return table["unsecured_senior"], "Unsecured senior non-FSE (40%)"

    coll_lower = collateral_type.lower()

    # Covered bonds — Art. 161(1B)
    if coll_lower in ("covered_bond", "covered_bonds"):
        return table["covered_bond"], "Covered bond (11.25%)"

    # Financial collateral
    if coll_lower in ("financial_collateral", "cash", "deposit", "gold"):
        return table["financial_collateral"], "Financial collateral (0%)"

    # Receivables
    if coll_lower in ("receivables", "trade_receivables"):
        return table["receivables"], "Receivables (20%)"

    # Real estate
    if coll_lower in ("residential_re", "rre", "residential"):
        return table["residential_re"], "Residential RE (20%)"

    if coll_lower in ("commercial_re", "cre", "commercial"):
        return table["commercial_re"], "Commercial RE (20%)"

    if coll_lower in ("real_estate", "property"):
        return table["residential_re"], "Real estate (20%)"

    # Other physical collateral
    if coll_lower in ("other_physical", "equipment", "inventory"):
        return table["other_physical"], "Other physical (25%)"

    # Unknown — treat as unsecured (with FSE distinction)
    if is_financial_sector_entity:
        return table["unsecured_senior_fse"], "Unknown collateral -> unsecured FSE (45%)"
    return table["unsecured_senior"], "Unknown collateral -> unsecured non-FSE (40%)"


def get_b31_vs_crr_lgd_comparison() -> pl.DataFrame:
    """Get a comparison DataFrame showing CRR vs Basel 3.1 FIRB LGD values.

    Useful for audit, reporting, and validation of the B31 LGD changes.

    Returns:
        DataFrame with columns: collateral_type, crr_lgd, b31_lgd, change_bps
    """
    from .crr_firb_lgd import FIRB_SUPERVISORY_LGD

    comparison_rows = []
    for key in FIRB_SUPERVISORY_LGD:
        crr_val = float(FIRB_SUPERVISORY_LGD[key])
        b31_val = float(BASEL31_FIRB_SUPERVISORY_LGD.get(key, FIRB_SUPERVISORY_LGD[key]))
        comparison_rows.append(
            {
                "collateral_type": key,
                "crr_lgd": crr_val,
                "b31_lgd": b31_val,
                "change_bps": round((b31_val - crr_val) * 10000),
            }
        )

    # Add FSE-specific entry (only in B31)
    comparison_rows.append(
        {
            "collateral_type": "unsecured_senior_fse",
            "crr_lgd": float(FIRB_SUPERVISORY_LGD["unsecured_senior"]),
            "b31_lgd": float(BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior_fse"]),
            "change_bps": 0,
        }
    )

    return pl.DataFrame(comparison_rows).with_columns(
        [
            pl.col("crr_lgd").cast(pl.Float64),
            pl.col("b31_lgd").cast(pl.Float64),
            pl.col("change_bps").cast(pl.Int32),
        ]
    )
