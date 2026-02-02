"""
CRR equity risk weight tables (CRR Art. 133, 155).

Provides risk weight lookup tables for equity exposures under two approaches:

1. Article 133 - Standardised Approach (SA):
   - Central bank: 0%
   - Listed/Exchange-traded/Government-supported: 100%
   - Unlisted: 250%
   - Speculative: 400%

2. Article 155 - IRB Simple Risk Weight Method:
   - Private equity (diversified portfolio): 190%
   - Exchange-traded: 290%
   - Other equity: 370%

References:
    - CRR Art. 133: Equity exposures under SA
    - CRR Art. 155: Simple risk weight approach under IRB
    - EBA Q&A 2023_6716: Strategic equity treatment
"""

from decimal import Decimal

import polars as pl

from rwa_calc.domain.enums import EquityType


# =============================================================================
# ARTICLE 133 - STANDARDISED APPROACH RISK WEIGHTS
# =============================================================================

SA_EQUITY_RISK_WEIGHTS: dict[EquityType, Decimal] = {
    EquityType.CENTRAL_BANK: Decimal("0.00"),
    EquityType.LISTED: Decimal("1.00"),
    EquityType.EXCHANGE_TRADED: Decimal("1.00"),
    EquityType.GOVERNMENT_SUPPORTED: Decimal("1.00"),
    EquityType.UNLISTED: Decimal("2.50"),
    EquityType.SPECULATIVE: Decimal("4.00"),
    EquityType.PRIVATE_EQUITY: Decimal("2.50"),
    EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("2.50"),
    EquityType.CIU: Decimal("2.50"),
    EquityType.OTHER: Decimal("2.50"),
}


# =============================================================================
# ARTICLE 155 - IRB SIMPLE RISK WEIGHT METHOD
# =============================================================================

IRB_SIMPLE_EQUITY_RISK_WEIGHTS: dict[EquityType, Decimal] = {
    EquityType.CENTRAL_BANK: Decimal("0.00"),
    EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("1.90"),
    EquityType.PRIVATE_EQUITY: Decimal("3.70"),
    EquityType.EXCHANGE_TRADED: Decimal("2.90"),
    EquityType.LISTED: Decimal("2.90"),
    EquityType.GOVERNMENT_SUPPORTED: Decimal("1.90"),
    EquityType.UNLISTED: Decimal("3.70"),
    EquityType.SPECULATIVE: Decimal("3.70"),
    EquityType.CIU: Decimal("3.70"),
    EquityType.OTHER: Decimal("3.70"),
}


# =============================================================================
# LOOKUP FUNCTIONS
# =============================================================================


def get_equity_risk_weights(approach: str = "sa") -> dict[EquityType, Decimal]:
    """
    Get equity risk weight dictionary for the specified approach.

    Args:
        approach: Either "sa" (Article 133) or "irb_simple" (Article 155)

    Returns:
        Dictionary mapping EquityType to risk weight as Decimal
    """
    if approach.lower() == "irb_simple":
        return IRB_SIMPLE_EQUITY_RISK_WEIGHTS.copy()
    return SA_EQUITY_RISK_WEIGHTS.copy()


def lookup_equity_rw(
    equity_type: str | EquityType,
    approach: str = "sa",
    is_diversified: bool = False,
) -> Decimal:
    """
    Look up risk weight for an equity exposure.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        equity_type: Equity type as string or EquityType enum
        approach: Either "sa" (Article 133) or "irb_simple" (Article 155)
        is_diversified: For private_equity, whether in diversified portfolio
                        (only affects IRB Simple - 190% vs 370%)

    Returns:
        Risk weight as Decimal
    """
    if isinstance(equity_type, str):
        try:
            eq_type = EquityType(equity_type.lower())
        except ValueError:
            eq_type = EquityType.OTHER
    else:
        eq_type = equity_type

    if eq_type == EquityType.PRIVATE_EQUITY and is_diversified:
        eq_type = EquityType.PRIVATE_EQUITY_DIVERSIFIED

    weights = get_equity_risk_weights(approach)
    return weights.get(eq_type, weights[EquityType.OTHER])


# =============================================================================
# DATAFRAME GENERATORS FOR JOINS
# =============================================================================


def _create_sa_equity_df() -> pl.DataFrame:
    """Create SA equity risk weight lookup DataFrame."""
    return pl.DataFrame({
        "equity_type": [e.value for e in EquityType],
        "risk_weight": [float(SA_EQUITY_RISK_WEIGHTS[e]) for e in EquityType],
        "approach": ["sa"] * len(EquityType),
    }).with_columns([
        pl.col("risk_weight").cast(pl.Float64),
    ])


def _create_irb_simple_equity_df() -> pl.DataFrame:
    """Create IRB Simple equity risk weight lookup DataFrame."""
    return pl.DataFrame({
        "equity_type": [e.value for e in EquityType],
        "risk_weight": [float(IRB_SIMPLE_EQUITY_RISK_WEIGHTS[e]) for e in EquityType],
        "approach": ["irb_simple"] * len(EquityType),
    }).with_columns([
        pl.col("risk_weight").cast(pl.Float64),
    ])


def get_equity_rw_table(approach: str = "sa") -> pl.DataFrame:
    """
    Get equity risk weight lookup table as DataFrame.

    Args:
        approach: Either "sa" (Article 133) or "irb_simple" (Article 155)

    Returns:
        DataFrame with columns: equity_type, risk_weight, approach
    """
    if approach.lower() == "irb_simple":
        return _create_irb_simple_equity_df()
    return _create_sa_equity_df()


def get_combined_equity_rw_table() -> pl.DataFrame:
    """
    Get combined equity risk weight table with both approaches.

    Returns:
        DataFrame with columns: equity_type, risk_weight, approach
        Contains rows for both SA and IRB_SIMPLE approaches.
    """
    return pl.concat([
        _create_sa_equity_df(),
        _create_irb_simple_equity_df(),
    ])
