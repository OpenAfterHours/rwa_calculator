"""
CRR Specialised Lending Slotting risk weights (CRR Art. 153(5)).

Provides slotting risk weight lookup tables as Polars DataFrames for efficient
joins in the RWA calculation pipeline.

CRR Art. 153(5) defines two tables with maturity-based splits:
    Table 1 - Non-HVCRE specialised lending (<2.5yr and >=2.5yr remaining maturity)
    Table 2 - HVCRE (<2.5yr and >=2.5yr remaining maturity)

Reference:
    CRR Art. 153(5): Slotting approach for specialised lending exposures
"""

from decimal import Decimal

import polars as pl

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


def _create_slotting_df() -> pl.DataFrame:
    """Create slotting risk weight lookup DataFrame with maturity splits."""
    rows = [
        # Non-HVCRE, >= 2.5yr (CRR Art. 153(5) Table 1)
        {"slotting_category": "strong", "is_hvcre": False, "is_short_maturity": False,
         "risk_weight": 0.70, "description": "Strong >= 2.5yr"},
        {"slotting_category": "good", "is_hvcre": False, "is_short_maturity": False,
         "risk_weight": 0.90, "description": "Good >= 2.5yr"},
        {"slotting_category": "satisfactory", "is_hvcre": False, "is_short_maturity": False,
         "risk_weight": 1.15, "description": "Satisfactory >= 2.5yr"},
        {"slotting_category": "weak", "is_hvcre": False, "is_short_maturity": False,
         "risk_weight": 2.50, "description": "Weak >= 2.5yr"},
        {"slotting_category": "default", "is_hvcre": False, "is_short_maturity": False,
         "risk_weight": 0.00, "description": "Default >= 2.5yr"},

        # Non-HVCRE, < 2.5yr (CRR Art. 153(5) Table 1)
        {"slotting_category": "strong", "is_hvcre": False, "is_short_maturity": True,
         "risk_weight": 0.50, "description": "Strong < 2.5yr"},
        {"slotting_category": "good", "is_hvcre": False, "is_short_maturity": True,
         "risk_weight": 0.70, "description": "Good < 2.5yr"},
        {"slotting_category": "satisfactory", "is_hvcre": False, "is_short_maturity": True,
         "risk_weight": 1.15, "description": "Satisfactory < 2.5yr"},
        {"slotting_category": "weak", "is_hvcre": False, "is_short_maturity": True,
         "risk_weight": 2.50, "description": "Weak < 2.5yr"},
        {"slotting_category": "default", "is_hvcre": False, "is_short_maturity": True,
         "risk_weight": 0.00, "description": "Default < 2.5yr"},

        # HVCRE, >= 2.5yr (CRR Art. 153(5) Table 2)
        {"slotting_category": "strong", "is_hvcre": True, "is_short_maturity": False,
         "risk_weight": 0.95, "description": "HVCRE Strong >= 2.5yr"},
        {"slotting_category": "good", "is_hvcre": True, "is_short_maturity": False,
         "risk_weight": 1.20, "description": "HVCRE Good >= 2.5yr"},
        {"slotting_category": "satisfactory", "is_hvcre": True, "is_short_maturity": False,
         "risk_weight": 1.40, "description": "HVCRE Satisfactory >= 2.5yr"},
        {"slotting_category": "weak", "is_hvcre": True, "is_short_maturity": False,
         "risk_weight": 2.50, "description": "HVCRE Weak >= 2.5yr"},
        {"slotting_category": "default", "is_hvcre": True, "is_short_maturity": False,
         "risk_weight": 0.00, "description": "HVCRE Default >= 2.5yr"},

        # HVCRE, < 2.5yr (CRR Art. 153(5) Table 2)
        {"slotting_category": "strong", "is_hvcre": True, "is_short_maturity": True,
         "risk_weight": 0.70, "description": "HVCRE Strong < 2.5yr"},
        {"slotting_category": "good", "is_hvcre": True, "is_short_maturity": True,
         "risk_weight": 0.95, "description": "HVCRE Good < 2.5yr"},
        {"slotting_category": "satisfactory", "is_hvcre": True, "is_short_maturity": True,
         "risk_weight": 1.40, "description": "HVCRE Satisfactory < 2.5yr"},
        {"slotting_category": "weak", "is_hvcre": True, "is_short_maturity": True,
         "risk_weight": 2.50, "description": "HVCRE Weak < 2.5yr"},
        {"slotting_category": "default", "is_hvcre": True, "is_short_maturity": True,
         "risk_weight": 0.00, "description": "HVCRE Default < 2.5yr"},
    ]

    return pl.DataFrame(rows).with_columns([
        pl.col("risk_weight").cast(pl.Float64),
    ])


def get_slotting_table() -> pl.DataFrame:
    """
    Get slotting risk weight lookup table.

    Returns:
        DataFrame with columns: slotting_category, is_hvcre, is_short_maturity,
            risk_weight, description
    """
    return _create_slotting_df()


def get_slotting_table_by_type() -> dict[str, pl.DataFrame]:
    """
    Get slotting tables split by HVCRE/non-HVCRE.

    Returns:
        Dictionary with "standard" and "hvcre" DataFrames
    """
    full_table = _create_slotting_df()
    return {
        "standard": full_table.filter(pl.col("is_hvcre") == False),
        "hvcre": full_table.filter(pl.col("is_hvcre") == True),
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
        table = SLOTTING_RISK_WEIGHTS_HVCRE_SHORT if is_short_maturity else SLOTTING_RISK_WEIGHTS_HVCRE
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


# =============================================================================
# SPECIALISED LENDING SUB-CLASSES
# =============================================================================

SPECIALISED_LENDING_TYPES: dict[str, str] = {
    "project_finance": "Project Finance - Large, complex capital expenditure",
    "object_finance": "Object Finance - Ships, aircraft, satellites",
    "commodities_finance": "Commodities Finance - Structured financing of reserves",
    "income_producing_re": "IPRE - Income Producing Real Estate",
    "hvcre": "HVCRE - High Volatility Commercial Real Estate",
}


def get_specialised_lending_types_df() -> pl.DataFrame:
    """
    Get DataFrame of specialised lending sub-classes.

    Returns:
        DataFrame with columns: sl_type, description, applies_hvcre
    """
    return pl.DataFrame({
        "sl_type": ["project_finance", "object_finance", "commodities_finance",
                    "income_producing_re", "hvcre"],
        "description": [
            "Project Finance - Large, complex capital expenditure",
            "Object Finance - Ships, aircraft, satellites",
            "Commodities Finance - Structured financing of reserves",
            "IPRE - Income Producing Real Estate",
            "HVCRE - High Volatility Commercial Real Estate",
        ],
        "applies_hvcre": [False, False, False, False, True],
    })
