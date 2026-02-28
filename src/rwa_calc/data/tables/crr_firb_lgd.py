"""
CRR F-IRB Supervisory LGD values (CRR Art. 161).

Provides supervisory LGD lookup tables for Foundation IRB approach
as Polars DataFrames for efficient joins in the RWA calculation pipeline.

Reference:
    CRR Art. 161: LGD for Foundation IRB approach
    CRR Art. 230: Overcollateralisation requirements for non-financial collateral
    CRE32.9-12: Basel 3.1 overcollateralisation and minimum thresholds
"""

from decimal import Decimal

import polars as pl

# =============================================================================
# F-IRB SUPERVISORY LGD VALUES (CRR Art. 161)
# =============================================================================

# Supervisory LGD values by seniority and collateral type
# CRR values (Art. 161)
FIRB_SUPERVISORY_LGD: dict[str, Decimal] = {
    # Unsecured exposures
    "unsecured_senior": Decimal("0.45"),  # 45% for senior unsecured
    "subordinated": Decimal("0.75"),  # 75% for subordinated
    # Fully secured by eligible financial collateral
    "financial_collateral": Decimal("0.00"),  # 0% (after haircuts)
    # Secured by receivables
    "receivables": Decimal("0.35"),  # 35%
    # Secured by real estate
    "residential_re": Decimal("0.35"),  # 35% for residential RE
    "commercial_re": Decimal("0.35"),  # 35% for commercial RE
    # Secured by other physical collateral
    "other_physical": Decimal("0.40"),  # 40% for other physical
}

# Basel 3.1 revised supervisory LGD values (CRE32.9-12, PRA PS9/24)
# Key changes from CRR: senior 45%→40%, receivables 35%→20%, RE 35%→20%,
# other physical 40%→25%
BASEL31_FIRB_SUPERVISORY_LGD: dict[str, Decimal] = {
    # Unsecured exposures
    "unsecured_senior": Decimal("0.40"),  # 40% (CRR: 45%)
    "subordinated": Decimal("0.75"),  # 75% (unchanged)
    # Fully secured by eligible financial collateral
    "financial_collateral": Decimal("0.00"),  # 0% (unchanged)
    # Secured by receivables
    "receivables": Decimal("0.20"),  # 20% (CRR: 35%)
    # Secured by real estate
    "residential_re": Decimal("0.20"),  # 20% (CRR: 35%)
    "commercial_re": Decimal("0.20"),  # 20% (CRR: 35%)
    # Secured by other physical collateral
    "other_physical": Decimal("0.25"),  # 25% (CRR: 40%)
}


def get_firb_lgd_table_for_framework(is_basel_3_1: bool = False) -> dict[str, Decimal]:
    """Get the F-IRB supervisory LGD table for the given framework.

    Args:
        is_basel_3_1: True for Basel 3.1 values, False for CRR values

    Returns:
        Dictionary of collateral_type -> supervisory LGD
    """
    return BASEL31_FIRB_SUPERVISORY_LGD if is_basel_3_1 else FIRB_SUPERVISORY_LGD


# =============================================================================
# F-IRB OVERCOLLATERALISATION REQUIREMENTS (CRR Art. 230 / CRE32.9-12)
# =============================================================================

# Overcollateralisation ratios: collateral must cover this multiple of EAD
# for the full reduced LGD to apply. effectively_secured = value / ratio.
FIRB_OVERCOLLATERALISATION_RATIOS: dict[str, float] = {
    "financial": 1.0,  # No overcollateralisation required
    "receivables": 1.25,  # 125% overcollateralisation
    "real_estate": 1.40,  # 140% overcollateralisation
    "other_physical": 1.40,  # 140% overcollateralisation
}

# Minimum collateralisation thresholds: if collateral value is below this
# fraction of EAD, non-financial collateral is ignored entirely.
FIRB_MIN_COLLATERALISATION_THRESHOLDS: dict[str, float] = {
    "financial": 0.0,  # No minimum threshold
    "receivables": 0.0,  # No minimum threshold
    "real_estate": 0.30,  # 30% minimum threshold
    "other_physical": 0.30,  # 30% minimum threshold
}

# PD floor under CRR (single floor for all classes)
CRR_PD_FLOOR: Decimal = Decimal("0.0003")  # 0.03%

# Maturity parameters
CRR_MATURITY_FLOOR: Decimal = Decimal("1.0")  # 1 year minimum
CRR_MATURITY_CAP: Decimal = Decimal("5.0")  # 5 year maximum


def _create_firb_lgd_df() -> pl.DataFrame:
    """Create F-IRB supervisory LGD lookup DataFrame.

    Includes overcollateralisation ratios and minimum thresholds per CRR Art. 230 / CRE32.9-12.
    """
    rows = [
        # Unsecured exposures
        {
            "collateral_type": "unsecured",
            "seniority": "senior",
            "lgd": 0.45,
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Unsecured senior claims",
        },
        {
            "collateral_type": "unsecured",
            "seniority": "subordinated",
            "lgd": 0.75,
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Subordinated claims",
        },
        # Financial collateral (eligible)
        {
            "collateral_type": "financial_collateral",
            "seniority": "senior",
            "lgd": 0.00,
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Eligible financial collateral (after haircuts)",
        },
        {
            "collateral_type": "cash",
            "seniority": "senior",
            "lgd": 0.00,
            "overcollateralisation_ratio": 1.0,
            "min_threshold": 0.0,
            "description": "Cash collateral",
        },
        # Receivables
        {
            "collateral_type": "receivables",
            "seniority": "senior",
            "lgd": 0.35,
            "overcollateralisation_ratio": 1.25,
            "min_threshold": 0.0,
            "description": "Secured by receivables",
        },
        # Real estate
        {
            "collateral_type": "residential_re",
            "seniority": "senior",
            "lgd": 0.35,
            "overcollateralisation_ratio": 1.40,
            "min_threshold": 0.30,
            "description": "Secured by residential real estate",
        },
        {
            "collateral_type": "commercial_re",
            "seniority": "senior",
            "lgd": 0.35,
            "overcollateralisation_ratio": 1.40,
            "min_threshold": 0.30,
            "description": "Secured by commercial real estate",
        },
        {
            "collateral_type": "real_estate",
            "seniority": "senior",
            "lgd": 0.35,
            "overcollateralisation_ratio": 1.40,
            "min_threshold": 0.30,
            "description": "Secured by real estate (general)",
        },
        # Other physical collateral
        {
            "collateral_type": "other_physical",
            "seniority": "senior",
            "lgd": 0.40,
            "overcollateralisation_ratio": 1.40,
            "min_threshold": 0.30,
            "description": "Other eligible physical collateral",
        },
    ]

    return pl.DataFrame(rows).with_columns(
        [
            pl.col("lgd").cast(pl.Float64),
            pl.col("overcollateralisation_ratio").cast(pl.Float64),
            pl.col("min_threshold").cast(pl.Float64),
        ]
    )


def get_firb_lgd_table() -> pl.DataFrame:
    """
    Get F-IRB supervisory LGD lookup table.

    Returns:
        DataFrame with columns: collateral_type, seniority, lgd, description
    """
    return _create_firb_lgd_df()


def lookup_firb_lgd(
    collateral_type: str | None = None,
    is_subordinated: bool = False,
    is_basel_3_1: bool = False,
) -> Decimal:
    """
    Look up F-IRB supervisory LGD.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        collateral_type: Type of collateral securing the exposure (None = unsecured)
        is_subordinated: Whether the exposure is subordinated
        is_basel_3_1: Whether to use Basel 3.1 revised values (CRE32.9-12)

    Returns:
        Supervisory LGD as Decimal
    """
    table = BASEL31_FIRB_SUPERVISORY_LGD if is_basel_3_1 else FIRB_SUPERVISORY_LGD

    # Subordinated always gets 75% regardless of collateral
    if is_subordinated:
        return table["subordinated"]

    # No collateral - senior unsecured
    if collateral_type is None:
        return table["unsecured_senior"]

    coll_lower = collateral_type.lower()

    # Financial collateral
    if coll_lower in ("financial_collateral", "cash", "deposit", "gold"):
        return table["financial_collateral"]

    # Receivables
    if coll_lower in ("receivables", "trade_receivables"):
        return table["receivables"]

    # Real estate
    if coll_lower in ("residential_re", "rre", "residential"):
        return table["residential_re"]

    if coll_lower in ("commercial_re", "cre", "commercial"):
        return table["commercial_re"]

    if coll_lower in ("real_estate", "property"):
        return table["residential_re"]  # Default to residential

    # Other physical collateral
    if coll_lower in ("other_physical", "equipment", "inventory"):
        return table["other_physical"]

    # Unknown - treat as unsecured
    return table["unsecured_senior"]


def _get_overcollateralisation_params(collateral_type: str) -> tuple[float, float]:
    """
    Get overcollateralisation ratio and minimum threshold for a collateral type.

    Args:
        collateral_type: Type of collateral

    Returns:
        Tuple of (overcollateralisation_ratio, min_threshold)
    """
    coll_lower = collateral_type.lower()

    # Financial collateral
    if coll_lower in (
        "financial_collateral",
        "cash",
        "deposit",
        "gold",
        "government_bond",
        "corporate_bond",
        "equity",
    ):
        return FIRB_OVERCOLLATERALISATION_RATIOS[
            "financial"
        ], FIRB_MIN_COLLATERALISATION_THRESHOLDS["financial"]

    # Receivables
    if coll_lower in ("receivables", "trade_receivables"):
        return FIRB_OVERCOLLATERALISATION_RATIOS[
            "receivables"
        ], FIRB_MIN_COLLATERALISATION_THRESHOLDS["receivables"]

    # Real estate
    if coll_lower in (
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
    ):
        return FIRB_OVERCOLLATERALISATION_RATIOS[
            "real_estate"
        ], FIRB_MIN_COLLATERALISATION_THRESHOLDS["real_estate"]

    # Other physical
    if coll_lower in ("other_physical", "equipment", "inventory", "other"):
        return FIRB_OVERCOLLATERALISATION_RATIOS[
            "other_physical"
        ], FIRB_MIN_COLLATERALISATION_THRESHOLDS["other_physical"]

    # Unknown: treat as unsecured (no overcollateralisation benefit)
    return 1.0, 0.0


def calculate_effective_lgd_secured(
    base_lgd_unsecured: Decimal,
    collateral_value_adjusted: Decimal,
    ead: Decimal,
    collateral_type: str,
    collateral_lgd: Decimal | None = None,
) -> tuple[Decimal, str]:
    """
    Calculate effective LGD for partially secured exposure.

    For F-IRB, when collateral covers part of the exposure:
    - Secured portion: use collateral-specific LGD
    - Unsecured portion: use 45% (senior) or 75% (subordinated)

    Non-financial collateral requires overcollateralisation (CRR Art. 230 / CRE32.9-12):
    - Real estate: 140% overcollateralisation, 30% minimum threshold
    - Receivables: 125% overcollateralisation, no minimum threshold
    - Other physical: 140% overcollateralisation, 30% minimum threshold
    - Financial: no overcollateralisation required

    Args:
        base_lgd_unsecured: LGD for unsecured portion (45% or 75%)
        collateral_value_adjusted: Adjusted collateral value (after haircuts)
        ead: Exposure at default
        collateral_type: Type of collateral
        collateral_lgd: Override LGD for secured portion (optional)

    Returns:
        Tuple of (effective_lgd, description)
    """
    if ead <= 0:
        return base_lgd_unsecured, "Zero EAD"

    # Determine LGD for secured portion
    if collateral_lgd is not None:
        lgd_secured = collateral_lgd
    else:
        lgd_secured = lookup_firb_lgd(collateral_type, is_subordinated=False)

    # Apply overcollateralisation and minimum threshold
    overcoll_ratio, min_threshold = _get_overcollateralisation_params(collateral_type)

    # Minimum threshold check: if collateral < threshold * EAD, ignore it
    if min_threshold > 0 and collateral_value_adjusted < Decimal(str(min_threshold)) * ead:
        return base_lgd_unsecured, f"Below min threshold ({min_threshold:.0%} of EAD)"

    # Effectively secured = adjusted_value / overcollateralisation_ratio
    effectively_secured = collateral_value_adjusted / Decimal(str(overcoll_ratio))

    # Calculate portions
    secured_portion = min(effectively_secured, ead)
    unsecured_portion = max(ead - effectively_secured, Decimal("0"))

    # Weighted average LGD
    if secured_portion + unsecured_portion > 0:
        effective_lgd = (
            lgd_secured * secured_portion + base_lgd_unsecured * unsecured_portion
        ) / ead
    else:
        effective_lgd = base_lgd_unsecured

    secured_pct = (secured_portion / ead * 100) if ead > 0 else Decimal("0")
    description = (
        f"Eff LGD: {effective_lgd:.1%} "
        f"(eff secured {secured_pct:.0f}% @ {lgd_secured:.0%}, "
        f"overcoll ratio {overcoll_ratio:.2f}, "
        f"unsecured @ {base_lgd_unsecured:.0%})"
    )

    return effective_lgd, description


# =============================================================================
# IRB PARAMETER FLOORS AND CAPS
# =============================================================================


def get_irb_parameters_df() -> pl.DataFrame:
    """
    Get IRB parameter floors and caps as DataFrame.

    Returns:
        DataFrame with regulatory parameter bounds
    """
    return pl.DataFrame(
        {
            "parameter": ["pd_floor", "maturity_floor", "maturity_cap"],
            "value": [0.0003, 1.0, 5.0],
            "unit": ["decimal", "years", "years"],
            "description": [
                "Minimum PD (0.03%)",
                "Minimum effective maturity",
                "Maximum effective maturity",
            ],
            "regulatory_reference": [
                "CRR Art. 163",
                "CRR Art. 162",
                "CRR Art. 162",
            ],
        }
    ).with_columns(
        [
            pl.col("value").cast(pl.Float64),
        ]
    )


def apply_pd_floor(pd: Decimal | float) -> Decimal:
    """
    Apply PD floor.

    Args:
        pd: Probability of default

    Returns:
        Floored PD (minimum 0.03%)
    """
    pd_decimal = Decimal(str(pd)) if not isinstance(pd, Decimal) else pd
    return max(pd_decimal, CRR_PD_FLOOR)


def apply_maturity_bounds(maturity: Decimal | float) -> Decimal:
    """
    Apply maturity floor and cap.

    Args:
        maturity: Effective maturity in years

    Returns:
        Bounded maturity (1-5 years)
    """
    mat_decimal = Decimal(str(maturity)) if not isinstance(maturity, Decimal) else maturity
    return max(CRR_MATURITY_FLOOR, min(CRR_MATURITY_CAP, mat_decimal))
