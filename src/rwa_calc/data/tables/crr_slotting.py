"""
CRR Specialised Lending Slotting risk weights and expected loss rates.

Provides slotting risk weight constants (Art. 153(5)) and expected loss rate
constants (Art. 158(6)) with scalar lookup functions.

CRR Art. 153(5) defines two tables with maturity-based splits:
    Table 1 - Non-HVCRE specialised lending (<2.5yr and >=2.5yr remaining maturity)
    Table 2 - HVCRE (<2.5yr and >=2.5yr remaining maturity)

CRR Art. 158(6), Table B defines expected loss rates:
    Non-HVCRE - maturity-dependent (<2.5yr and >=2.5yr)
    HVCRE - flat (no maturity split)

References:
    CRR Art. 153(5): Slotting approach for specialised lending exposures
    CRR Art. 158(6), Table B: Expected loss rates for slotting exposures
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.domain.enums import SlottingCategory

# =============================================================================
# SLOTTING RISK WEIGHTS (CRR Art. 153(5))
# =============================================================================

# Non-HVCRE slotting risk weights — Table 1
# Remaining maturity >= 2.5 years
SLOTTING_RISK_WEIGHTS: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.70"),
    SlottingCategory.GOOD: Decimal("0.90"),
    SlottingCategory.SATISFACTORY: Decimal("1.15"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),  # 100% provisioned
}

# Remaining maturity < 2.5 years
SLOTTING_RISK_WEIGHTS_SHORT: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.50"),
    SlottingCategory.GOOD: Decimal("0.70"),
    SlottingCategory.SATISFACTORY: Decimal("1.15"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}

# HVCRE slotting risk weights — Table 2
# Remaining maturity >= 2.5 years
SLOTTING_RISK_WEIGHTS_HVCRE: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.95"),
    SlottingCategory.GOOD: Decimal("1.20"),
    SlottingCategory.SATISFACTORY: Decimal("1.40"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}

# Remaining maturity < 2.5 years
SLOTTING_RISK_WEIGHTS_HVCRE_SHORT: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.70"),
    SlottingCategory.GOOD: Decimal("0.95"),
    SlottingCategory.SATISFACTORY: Decimal("1.40"),
    SlottingCategory.WEAK: Decimal("2.50"),
    SlottingCategory.DEFAULT: Decimal("0.00"),
}


# =============================================================================
# SLOTTING EXPECTED LOSS RATES (CRR Art. 158(6), Table B)
# =============================================================================

# Non-HVCRE EL rates — Table B
# Remaining maturity >= 2.5 years
SLOTTING_EL_RATES: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.004"),  # 0.4%
    SlottingCategory.GOOD: Decimal("0.008"),  # 0.8%
    SlottingCategory.SATISFACTORY: Decimal("0.028"),  # 2.8%
    SlottingCategory.WEAK: Decimal("0.08"),  # 8%
    SlottingCategory.DEFAULT: Decimal("0.50"),  # 50%
}

# Remaining maturity < 2.5 years
SLOTTING_EL_RATES_SHORT: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.0"),  # 0%
    SlottingCategory.GOOD: Decimal("0.004"),  # 0.4%
    SlottingCategory.SATISFACTORY: Decimal("0.028"),  # 2.8%
    SlottingCategory.WEAK: Decimal("0.08"),  # 8%
    SlottingCategory.DEFAULT: Decimal("0.50"),  # 50%
}

# HVCRE EL rates — Table B (flat, no maturity split)
# UK CRR has no HVCRE concept (Art. 158 was omitted by SI 2021/1078); these
# values follow the PRA PS1/26 Art. 158(6) Table B HVCRE row which is the only
# extant UK regulatory source — flat 0.4% across both Strong and Good
# (subgrade columns A/B/C/D all 0.4% for HVCRE).
SLOTTING_EL_RATES_HVCRE: dict[SlottingCategory, Decimal] = {
    SlottingCategory.STRONG: Decimal("0.004"),  # 0.4%
    SlottingCategory.GOOD: Decimal("0.004"),  # 0.4%
    SlottingCategory.SATISFACTORY: Decimal("0.028"),  # 2.8%
    SlottingCategory.WEAK: Decimal("0.08"),  # 8%
    SlottingCategory.DEFAULT: Decimal("0.50"),  # 50%
}


def lookup_slotting_rw(
    category: str | SlottingCategory,
    is_hvcre: bool = False,
    is_short_maturity: bool = False,
) -> Decimal:
    """
    Look up slotting risk weight.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        category: Slotting category (strong, good, satisfactory, weak, default)
        is_hvcre: Whether this is high-volatility commercial real estate
        is_short_maturity: Whether remaining maturity < 2.5 years

    Returns:
        Risk weight as Decimal
    """
    # Normalize category to SlottingCategory enum
    if isinstance(category, str):
        try:
            cat_enum = SlottingCategory(category.lower())
        except ValueError:
            return Decimal("1.15")
    else:
        cat_enum = category

    # Select appropriate weight table
    if is_hvcre:
        table = (
            SLOTTING_RISK_WEIGHTS_HVCRE_SHORT if is_short_maturity else SLOTTING_RISK_WEIGHTS_HVCRE
        )
    else:
        table = SLOTTING_RISK_WEIGHTS_SHORT if is_short_maturity else SLOTTING_RISK_WEIGHTS

    return table.get(cat_enum, Decimal("1.15"))


def calculate_slotting_rwa(
    ead: Decimal,
    category: str | SlottingCategory,
    is_hvcre: bool = False,
    is_short_maturity: bool = False,
) -> tuple[Decimal, Decimal, str]:
    """
    Calculate RWA using slotting approach.

    Args:
        ead: Exposure at default
        category: Slotting category
        is_hvcre: Whether this is HVCRE
        is_short_maturity: Whether remaining maturity < 2.5 years

    Returns:
        Tuple of (rwa, risk_weight, description)
    """
    risk_weight = lookup_slotting_rw(category, is_hvcre, is_short_maturity)
    rwa = ead * risk_weight

    hvcre_str = " (HVCRE)" if is_hvcre else ""
    mat_str = " <2.5yr" if is_short_maturity else ""
    cat_str = category.value if isinstance(category, SlottingCategory) else category
    description = f"Slotting{hvcre_str}{mat_str} {cat_str}: {risk_weight:.0%} RW"

    return rwa, risk_weight, description


def lookup_slotting_el_rate(
    category: str | SlottingCategory,
    is_hvcre: bool = False,
    is_short_maturity: bool = False,
) -> Decimal:
    """
    Look up slotting expected loss rate per CRR Art. 158(6), Table B.

    Args:
        category: Slotting category (strong, good, satisfactory, weak, default)
        is_hvcre: Whether this is high-volatility commercial real estate
        is_short_maturity: Whether remaining maturity < 2.5 years

    Returns:
        Expected loss rate as Decimal (e.g. 0.004 for 0.4%)
    """
    if isinstance(category, str):
        try:
            cat_enum = SlottingCategory(category.lower())
        except ValueError:
            return Decimal("0.028")  # Satisfactory default
    else:
        cat_enum = category

    if is_hvcre:
        # HVCRE has flat EL rates (no maturity split)
        table = SLOTTING_EL_RATES_HVCRE
    else:
        table = SLOTTING_EL_RATES_SHORT if is_short_maturity else SLOTTING_EL_RATES

    return table.get(cat_enum, Decimal("0.028"))
