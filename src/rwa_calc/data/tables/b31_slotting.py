"""
Basel 3.1 Specialised Lending Slotting risk weights.

Provides slotting risk weight constants and scalar lookup functions for the
Basel 3.1 framework as implemented by PRA PS1/26.

PRA PS1/26 Art. 153(5) Table A defines two weight tables:
    Table A - All specialised lending (OF, PF, CF, IPRE) incl. pre-operational PF
    Table A (HVCRE) - High-volatility commercial real estate

Note: BCBS CRE33 defines a separate pre-operational PF table with higher weights
(Strong=80%, Good=100%, Satisfactory=120%, Weak=350%). PRA PS1/26 does NOT adopt
this distinction — all PF uses the standard Table A weights regardless of operational
status. The SA calculator handles pre-operational PF separately via Art. 122B(2)(c).

References:
    PRA PS1/26 Art. 153(5), Table A: Slotting risk weights
    BCBS CRE33.5-8: Supervisory slotting criteria (pre-op distinction not in PRA)
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.domain.enums import SlottingCategory

# =============================================================================
# BASEL 3.1 SLOTTING RISK WEIGHTS (BCBS CRE33)
# =============================================================================

# Non-HVCRE, operational (base table)
B31_SLOTTING_RISK_WEIGHTS: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.70"),
    SlottingCategory.GOOD: Decimal("0.90"),
    SlottingCategory.SATISFACTORY: Decimal("1.15"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}

# Project finance pre-operational phase — PRA PS1/26 Art. 153(5) Table A
# uses the SAME weights as operational PF. BCBS CRE33 had separate higher weights
# (80/100/120/350%) but PRA did not adopt this distinction.
B31_SLOTTING_RISK_WEIGHTS_PREOP: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.70"),
    SlottingCategory.GOOD: Decimal("0.90"),
    SlottingCategory.SATISFACTORY: Decimal("1.15"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}

# HVCRE
B31_SLOTTING_RISK_WEIGHTS_HVCRE: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.95"),
    SlottingCategory.GOOD: Decimal("1.20"),
    SlottingCategory.SATISFACTORY: Decimal("1.40"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}


def lookup_b31_slotting_rw(
    category: str | SlottingCategory,
    is_hvcre: bool = False,
    is_pre_operational: bool = False,
) -> Decimal:
    """
    Look up Basel 3.1 slotting risk weight.

    Convenience function for single lookups. For bulk processing,
    use the Polars namespace (``col("slotting_category").slotting.lookup_rw(...)``).

    Args:
        category: Slotting category (strong, good, satisfactory, weak, default)
        is_hvcre: Whether this is high-volatility commercial real estate
        is_pre_operational: Whether this is a pre-operational project finance exposure

    Returns:
        Risk weight as Decimal
    """
    if isinstance(category, str):
        try:
            cat_enum = SlottingCategory(category.lower())
        except ValueError:
            return Decimal("1.15")
    else:
        cat_enum = category

    if is_hvcre:
        table = B31_SLOTTING_RISK_WEIGHTS_HVCRE
    elif is_pre_operational:
        table = B31_SLOTTING_RISK_WEIGHTS_PREOP
    else:
        table = B31_SLOTTING_RISK_WEIGHTS

    return table.get(cat_enum, Decimal("1.15"))
