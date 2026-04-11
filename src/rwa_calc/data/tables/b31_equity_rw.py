"""
Basel 3.1 Equity Risk Weight Tables (PRA PS1/26 Art. 133).

Under Basel 3.1, all equity exposures must use the Standardised Approach
(IRB equity methods removed per Art. 147A / CRE20.58-62).

PRA PS1/26 Art. 133 SA equity risk weights:
- Art. 133(3): Standard equity = 250%
- Art. 133(4)/(5): Higher risk (speculative / PE / VC / unlisted <5yr) = 400%
- Art. 133(1): Subordinated debt / non-equity own funds = 150%
- Art. 133(6): Central bank equity = 0%
- Legislative programme equity = 100%

Key PRA deviation from BCBS:
    PRA does not use BCBS CQS-differentiated speculative tiers.
    All higher-risk equity gets a flat 400% under PRA.

Note: PE/VC is always higher-risk under Art. 133(5) regardless of
diversification status. The 190% diversified PE rate only applied
under IRB Simple (Art. 155), which is removed under Basel 3.1.

References:
    - PRA PS1/26 Art. 133(3)-(6)
    - BCBS CRE20.58-62
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from rwa_calc.domain.enums import EquityType

# =============================================================================
# ARTICLE 133 - BASEL 3.1 SA EQUITY RISK WEIGHTS (PRA PS1/26)
# =============================================================================

B31_SA_EQUITY_RISK_WEIGHTS: dict[EquityType, Decimal] = {
    EquityType.CENTRAL_BANK: Decimal("0.00"),  # Art. 133(6): 0%
    EquityType.SUBORDINATED_DEBT: Decimal("1.50"),  # Art. 133(1): 150%
    EquityType.LISTED: Decimal("2.50"),  # Art. 133(3): 250% standard
    EquityType.EXCHANGE_TRADED: Decimal("2.50"),  # Art. 133(3): 250% standard
    EquityType.GOVERNMENT_SUPPORTED: Decimal("1.00"),  # Legislative programme: 100%
    EquityType.UNLISTED: Decimal("2.50"),  # Art. 133(3): 250% standard
    EquityType.SPECULATIVE: Decimal("4.00"),  # Art. 133(4): 400% higher risk
    EquityType.PRIVATE_EQUITY: Decimal("4.00"),  # Art. 133(5): 400% higher risk (PE/VC)
    EquityType.PRIVATE_EQUITY_DIVERSIFIED: Decimal("4.00"),  # Art. 133(5): 400% higher risk (PE/VC)
    EquityType.CIU: Decimal("12.50"),  # Art. 132(2): 1,250% fallback
    EquityType.OTHER: Decimal("2.50"),  # Art. 133(3): 250% standard
}


# =============================================================================
# LOOKUP FUNCTIONS
# =============================================================================


def get_b31_equity_risk_weights() -> dict[EquityType, Decimal]:
    """Get Basel 3.1 SA equity risk weight dictionary.

    Returns:
        Dictionary mapping EquityType to risk weight as Decimal
    """
    return B31_SA_EQUITY_RISK_WEIGHTS.copy()


def lookup_b31_equity_rw(
    equity_type: str | EquityType,
    is_diversified: bool = False,
) -> Decimal:
    """Look up Basel 3.1 SA risk weight for an equity exposure.

    Args:
        equity_type: Equity type as string or EquityType enum
        is_diversified: For private_equity, whether in diversified portfolio
                        (both map to 400% under B31 as PE/VC is always higher-risk;
                        the 190% diversified rate only applied under CRR IRB Simple)

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

    return B31_SA_EQUITY_RISK_WEIGHTS.get(eq_type, B31_SA_EQUITY_RISK_WEIGHTS[EquityType.OTHER])


# =============================================================================
# DATAFRAME GENERATORS FOR JOINS
# =============================================================================


def get_b31_equity_rw_table() -> pl.DataFrame:
    """Get Basel 3.1 SA equity risk weight lookup table as DataFrame.

    Returns:
        DataFrame with columns: equity_type, risk_weight, approach
    """
    return pl.DataFrame(
        {
            "equity_type": [e.value for e in EquityType],
            "risk_weight": [float(B31_SA_EQUITY_RISK_WEIGHTS[e]) for e in EquityType],
            "approach": ["sa"] * len(EquityType),
        }
    ).with_columns(
        pl.col("risk_weight").cast(pl.Float64),
    )
