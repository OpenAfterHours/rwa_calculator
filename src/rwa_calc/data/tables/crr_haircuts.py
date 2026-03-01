"""
CRM supervisory haircuts (CRR Art. 224 / CRE22.52-53).

Provides collateral haircut lookup tables as Polars DataFrames for efficient
joins in the RWA calculation pipeline. Supports both CRR and Basel 3.1 frameworks.

Key differences under Basel 3.1 (CRE22.52-53):
- 5 maturity bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+) instead of CRR's 3 (0-1y, 1-5y, 5y+)
- Higher haircuts for long-dated corporate bonds (CQS 1-2: 10%/12%, CQS 3: 15%)
- Higher equity haircuts (main index: 25%, other: 35%)
- Sovereign CQS 2-3 10y+ increased to 12%

Reference:
    CRR Art. 224: Supervisory haircuts under the Financial Collateral
    Comprehensive Method
    CRE22.52-53: Basel 3.1 supervisory haircuts
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

# =============================================================================
# CRR SUPERVISORY HAIRCUTS (CRR Art. 224)
# =============================================================================
# CRR uses 3 maturity bands: 0-1y, 1-5y, 5y+

COLLATERAL_HAIRCUTS: dict[str, Decimal] = {
    # Cash and equivalents
    "cash": Decimal("0.00"),
    "gold": Decimal("0.15"),
    # Government bonds by CQS and maturity band
    "govt_bond_cqs1_0_1y": Decimal("0.005"),
    "govt_bond_cqs1_1_5y": Decimal("0.02"),
    "govt_bond_cqs1_5y_plus": Decimal("0.04"),
    "govt_bond_cqs2_3_0_1y": Decimal("0.01"),
    "govt_bond_cqs2_3_1_5y": Decimal("0.03"),
    "govt_bond_cqs2_3_5y_plus": Decimal("0.06"),
    # Corporate bonds by CQS and maturity band
    "corp_bond_cqs1_2_0_1y": Decimal("0.01"),
    "corp_bond_cqs1_2_1_5y": Decimal("0.04"),
    "corp_bond_cqs1_2_5y_plus": Decimal("0.06"),
    "corp_bond_cqs3_0_1y": Decimal("0.02"),
    "corp_bond_cqs3_1_5y": Decimal("0.06"),
    "corp_bond_cqs3_5y_plus": Decimal("0.08"),
    # Equity
    "equity_main_index": Decimal("0.15"),
    "equity_other": Decimal("0.25"),
    # Other
    "receivables": Decimal("0.20"),
    "other_physical": Decimal("0.40"),
}

# =============================================================================
# BASEL 3.1 SUPERVISORY HAIRCUTS (CRE22.52-53)
# =============================================================================
# Basel 3.1 uses 5 maturity bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+

BASEL31_COLLATERAL_HAIRCUTS: dict[str, Decimal] = {
    # Cash and equivalents (unchanged)
    "cash": Decimal("0.00"),
    "gold": Decimal("0.15"),
    # Government bonds CQS 1 — same as CRR for short/medium, split long-dated
    "govt_bond_cqs1_0_1y": Decimal("0.005"),
    "govt_bond_cqs1_1_3y": Decimal("0.02"),
    "govt_bond_cqs1_3_5y": Decimal("0.02"),
    "govt_bond_cqs1_5_10y": Decimal("0.04"),
    "govt_bond_cqs1_10y_plus": Decimal("0.04"),
    # Government bonds CQS 2-3 — 10y+ increases from 6% to 12%
    "govt_bond_cqs2_3_0_1y": Decimal("0.01"),
    "govt_bond_cqs2_3_1_3y": Decimal("0.03"),
    "govt_bond_cqs2_3_3_5y": Decimal("0.04"),
    "govt_bond_cqs2_3_5_10y": Decimal("0.06"),
    "govt_bond_cqs2_3_10y_plus": Decimal("0.12"),
    # Corporate bonds CQS 1-2 — significant increases for long-dated
    "corp_bond_cqs1_2_0_1y": Decimal("0.01"),
    "corp_bond_cqs1_2_1_3y": Decimal("0.04"),
    "corp_bond_cqs1_2_3_5y": Decimal("0.06"),
    "corp_bond_cqs1_2_5_10y": Decimal("0.10"),
    "corp_bond_cqs1_2_10y_plus": Decimal("0.12"),
    # Corporate bonds CQS 3 — significant increases for long-dated
    "corp_bond_cqs3_0_1y": Decimal("0.02"),
    "corp_bond_cqs3_1_3y": Decimal("0.06"),
    "corp_bond_cqs3_3_5y": Decimal("0.08"),
    "corp_bond_cqs3_5_10y": Decimal("0.15"),
    "corp_bond_cqs3_10y_plus": Decimal("0.15"),
    # Equity — increased under Basel 3.1
    "equity_main_index": Decimal("0.25"),  # CRR: 15%
    "equity_other": Decimal("0.35"),  # CRR: 25%
    # Other (unchanged)
    "receivables": Decimal("0.20"),
    "other_physical": Decimal("0.40"),
}

# Currency mismatch haircut (CRR Art. 224 / CRE22.54) — same under both frameworks
FX_HAIRCUT: Decimal = Decimal("0.08")


def _create_haircut_df(is_basel_3_1: bool = False) -> pl.DataFrame:
    """Create haircut lookup DataFrame for the specified framework."""
    if is_basel_3_1:
        return _create_basel31_haircut_df()
    return _create_crr_haircut_df()


def _create_crr_haircut_df() -> pl.DataFrame:
    """Create CRR haircut lookup DataFrame (3 maturity bands)."""
    rows = [
        # Cash and gold
        {
            "collateral_type": "cash",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.00,
            "is_main_index": None,
        },
        {
            "collateral_type": "gold",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.15,
            "is_main_index": None,
        },
        # Government bonds CQS 1
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "0_1y",
            "haircut": 0.005,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "1_5y",
            "haircut": 0.02,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "5y_plus",
            "haircut": 0.04,
            "is_main_index": None,
        },
        # Government bonds CQS 2-3
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "1_5y",
            "haircut": 0.03,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "5y_plus",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "1_5y",
            "haircut": 0.03,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "5y_plus",
            "haircut": 0.06,
            "is_main_index": None,
        },
        # Corporate bonds CQS 1-2
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "1_5y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "5y_plus",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "1_5y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "5y_plus",
            "haircut": 0.06,
            "is_main_index": None,
        },
        # Corporate bonds CQS 3
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "0_1y",
            "haircut": 0.02,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "1_5y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "5y_plus",
            "haircut": 0.08,
            "is_main_index": None,
        },
        # Equity
        {
            "collateral_type": "equity",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.15,
            "is_main_index": True,
        },
        {
            "collateral_type": "equity",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.25,
            "is_main_index": False,
        },
        # Other
        {
            "collateral_type": "receivables",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.20,
            "is_main_index": None,
        },
        {
            "collateral_type": "other_physical",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.40,
            "is_main_index": None,
        },
    ]

    return pl.DataFrame(rows).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("haircut").cast(pl.Float64),
        ]
    )


def _create_basel31_haircut_df() -> pl.DataFrame:
    """Create Basel 3.1 haircut lookup DataFrame (5 maturity bands per CRE22.52-53)."""
    rows = [
        # Cash and gold (unchanged)
        {
            "collateral_type": "cash",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.00,
            "is_main_index": None,
        },
        {
            "collateral_type": "gold",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.15,
            "is_main_index": None,
        },
        # Government bonds CQS 1
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "0_1y",
            "haircut": 0.005,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "1_3y",
            "haircut": 0.02,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "3_5y",
            "haircut": 0.02,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "5_10y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 1,
            "maturity_band": "10y_plus",
            "haircut": 0.04,
            "is_main_index": None,
        },
        # Government bonds CQS 2-3
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "1_3y",
            "haircut": 0.03,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "3_5y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "5_10y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 2,
            "maturity_band": "10y_plus",
            "haircut": 0.12,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "1_3y",
            "haircut": 0.03,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "3_5y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "5_10y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "govt_bond",
            "cqs": 3,
            "maturity_band": "10y_plus",
            "haircut": 0.12,
            "is_main_index": None,
        },
        # Corporate bonds CQS 1-2
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "1_3y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "3_5y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "5_10y",
            "haircut": 0.10,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 1,
            "maturity_band": "10y_plus",
            "haircut": 0.12,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "0_1y",
            "haircut": 0.01,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "1_3y",
            "haircut": 0.04,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "3_5y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "5_10y",
            "haircut": 0.10,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 2,
            "maturity_band": "10y_plus",
            "haircut": 0.12,
            "is_main_index": None,
        },
        # Corporate bonds CQS 3
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "0_1y",
            "haircut": 0.02,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "1_3y",
            "haircut": 0.06,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "3_5y",
            "haircut": 0.08,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "5_10y",
            "haircut": 0.15,
            "is_main_index": None,
        },
        {
            "collateral_type": "corp_bond",
            "cqs": 3,
            "maturity_band": "10y_plus",
            "haircut": 0.15,
            "is_main_index": None,
        },
        # Equity — higher under Basel 3.1
        {
            "collateral_type": "equity",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.25,
            "is_main_index": True,
        },
        {
            "collateral_type": "equity",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.35,
            "is_main_index": False,
        },
        # Other (unchanged)
        {
            "collateral_type": "receivables",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.20,
            "is_main_index": None,
        },
        {
            "collateral_type": "other_physical",
            "cqs": None,
            "maturity_band": None,
            "haircut": 0.40,
            "is_main_index": None,
        },
    ]

    return pl.DataFrame(rows).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("haircut").cast(pl.Float64),
        ]
    )


def get_haircut_table(is_basel_3_1: bool = False) -> pl.DataFrame:
    """
    Get collateral haircut lookup table for the given framework.

    Args:
        is_basel_3_1: True for Basel 3.1 haircuts (CRE22.52-53), False for CRR (Art. 224)

    Returns:
        DataFrame with columns: collateral_type, cqs, maturity_band, haircut, is_main_index
    """
    return _create_haircut_df(is_basel_3_1=is_basel_3_1)


def get_maturity_band(residual_maturity_years: float, is_basel_3_1: bool = False) -> str:
    """
    Determine maturity band from residual maturity.

    CRR uses 3 bands: 0-1y, 1-5y, 5y+
    Basel 3.1 uses 5 bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+

    Args:
        residual_maturity_years: Residual maturity in years
        is_basel_3_1: True for Basel 3.1 maturity bands

    Returns:
        Maturity band string
    """
    if is_basel_3_1:
        if residual_maturity_years <= 1.0:
            return "0_1y"
        elif residual_maturity_years <= 3.0:
            return "1_3y"
        elif residual_maturity_years <= 5.0:
            return "3_5y"
        elif residual_maturity_years <= 10.0:
            return "5_10y"
        else:
            return "10y_plus"
    else:
        if residual_maturity_years <= 1.0:
            return "0_1y"
        elif residual_maturity_years <= 5.0:
            return "1_5y"
        else:
            return "5y_plus"


def lookup_collateral_haircut(
    collateral_type: str,
    cqs: int | None = None,
    residual_maturity_years: float | None = None,
    is_main_index: bool = False,
    is_basel_3_1: bool = False,
) -> Decimal:
    """
    Look up supervisory haircut for collateral.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        collateral_type: Type of collateral
        cqs: Credit quality step of issuer (for debt securities)
        residual_maturity_years: Remaining maturity in years
        is_main_index: For equity, whether it's on a main index
        is_basel_3_1: Whether to use Basel 3.1 haircuts (CRE22.52-53)

    Returns:
        Haircut as Decimal
    """
    table = BASEL31_COLLATERAL_HAIRCUTS if is_basel_3_1 else COLLATERAL_HAIRCUTS
    coll_lower = collateral_type.lower()

    # Cash - 0%
    if coll_lower in ("cash", "deposit"):
        return table["cash"]

    # Gold - 15%
    if coll_lower == "gold":
        return table["gold"]

    # Government bonds
    if coll_lower in ("govt_bond", "sovereign_bond", "government_bond", "gilt"):
        maturity = residual_maturity_years or 5.0
        maturity_band = get_maturity_band(maturity, is_basel_3_1=is_basel_3_1)

        if cqs == 1:
            key = f"govt_bond_cqs1_{maturity_band}"
        elif cqs in (2, 3):
            key = f"govt_bond_cqs2_3_{maturity_band}"
        else:
            # CQS 4+ or unrated - use higher haircut
            return Decimal("0.15")

        return table.get(key, Decimal("0.15"))

    # Corporate bonds
    if coll_lower in ("corp_bond", "corporate_bond"):
        maturity = residual_maturity_years or 5.0
        maturity_band = get_maturity_band(maturity, is_basel_3_1=is_basel_3_1)

        if cqs in (1, 2):
            key = f"corp_bond_cqs1_2_{maturity_band}"
        elif cqs == 3:
            key = f"corp_bond_cqs3_{maturity_band}"
        else:
            # Lower rated - not eligible or high haircut
            return Decimal("0.20")

        return table.get(key, Decimal("0.20"))

    # Equity
    if coll_lower in ("equity", "shares", "stock"):
        if is_main_index:
            return table["equity_main_index"]
        return table["equity_other"]

    # Receivables
    if coll_lower in ("receivables", "trade_receivables"):
        return table["receivables"]

    # Real estate (not typically haircut-based in CRM)
    if coll_lower in ("real_estate", "property", "rre", "cre"):
        return Decimal("0.00")

    # Other physical collateral
    return table["other_physical"]


def lookup_fx_haircut(
    exposure_currency: str,
    collateral_currency: str,
) -> Decimal:
    """
    Get FX mismatch haircut.

    Args:
        exposure_currency: Currency of exposure
        collateral_currency: Currency of collateral

    Returns:
        FX haircut (0% if same currency, 8% if different)
    """
    if exposure_currency.upper() == collateral_currency.upper():
        return Decimal("0.00")
    return FX_HAIRCUT


def calculate_adjusted_collateral_value(
    collateral_value: Decimal,
    collateral_haircut: Decimal,
    fx_haircut: Decimal = Decimal("0.00"),
) -> Decimal:
    """
    Calculate adjusted collateral value after haircuts.

    CRR Art. 223 formula: C_adjusted = C x (1 - Hc - Hfx)

    Args:
        collateral_value: Market value of collateral
        collateral_haircut: Collateral-specific haircut
        fx_haircut: FX mismatch haircut (default 0%)

    Returns:
        Adjusted collateral value
    """
    total_haircut = collateral_haircut + fx_haircut
    return collateral_value * (Decimal("1") - total_haircut)


def calculate_maturity_mismatch_adjustment(
    collateral_value: Decimal,
    collateral_maturity_years: float,
    exposure_maturity_years: float,
    minimum_maturity_years: float = 0.25,
) -> tuple[Decimal, str]:
    """
    Apply maturity mismatch adjustment (CRR Art. 238).

    Args:
        collateral_value: Adjusted collateral value
        collateral_maturity_years: Residual maturity of collateral
        exposure_maturity_years: Residual maturity of exposure
        minimum_maturity_years: Minimum maturity threshold (default 3 months)

    Returns:
        Tuple of (adjusted_value, description)

    Formula:
        If t < T: Adjusted = C x (t - 0.25) / (T - 0.25)
        Where t = collateral maturity, T = exposure maturity (capped at 5y)
    """
    # If collateral maturity >= exposure maturity, no adjustment
    if collateral_maturity_years >= exposure_maturity_years:
        return collateral_value, "No maturity mismatch adjustment"

    # If collateral maturity < 3 months, no protection
    if collateral_maturity_years < minimum_maturity_years:
        return Decimal("0"), "Collateral maturity < 3 months, no protection"

    # Apply adjustment
    t = max(collateral_maturity_years, minimum_maturity_years)
    T = min(max(exposure_maturity_years, minimum_maturity_years), 5.0)

    adjustment_factor = Decimal(str((t - 0.25) / (T - 0.25)))
    adjusted_value = collateral_value * adjustment_factor

    description = f"Maturity adj: {adjustment_factor:.3f} (t={t:.1f}y, T={T:.1f}y)"
    return adjusted_value, description
