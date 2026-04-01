"""
Basel 3.1 Specialised Lending Slotting risk weights (BCBS CRE33).

Provides slotting risk weight constants and scalar lookup functions for the
Basel 3.1 framework as implemented by PRA PS1/26.

Basel 3.1 defines three weight tables:
    Table 1 - Non-HVCRE operational specialised lending
    Table 2 - Project finance pre-operational phase
    Table 3 - HVCRE

References:
    BCBS CRE33.5-8: Supervisory slotting criteria for specialised lending
    PRA PS1/26 Appendix 1: UK implementation
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

# Project finance pre-operational phase
B31_SLOTTING_RISK_WEIGHTS_PREOP: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.80"),
    SlottingCategory.GOOD: Decimal("1.00"),
    SlottingCategory.SATISFACTORY: Decimal("1.20"),
    SlottingCategory.WEAK: Decimal("3.50"),
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
