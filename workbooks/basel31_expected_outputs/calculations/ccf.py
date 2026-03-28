"""
Credit Conversion Factor (CCF) calculations.

Implements CCF lookup and EAD calculation for off-balance sheet items
per CRE20.93-98.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.rwa_expected_outputs.data.regulatory_params import CCF_VALUES


def get_ccf(ccf_category: str) -> float:
    """
    Get Credit Conversion Factor for off-balance sheet item.

    Args:
        ccf_category: Category from contingent exposure data

    Returns:
        CCF as decimal (e.g., 0.40 for 40%)

    Reference: CRE20.93-98

    CCF Categories:
    - 0%: Unconditionally cancellable commitments
    - 10%: Basel 3.1 retail unconditionally cancellable
    - 20%: Short-term trade letters of credit
    - 40%: Committed facilities, NIF/RUF
    - 50%: Performance-related contingencies
    - 100%: Direct credit substitutes, acceptances
    """
    # Direct lookup
    if ccf_category in CCF_VALUES:
        return CCF_VALUES[ccf_category]

    # Category mapping for common names
    category_map = {
        # 0% CCF
        "ccf_0": 0.00,
        "unconditionally_cancellable": 0.00,
        "uncommitted": 0.00,
        # 10% CCF (Basel 3.1)
        "ccf_10": 0.10,
        "retail_cancellable": 0.10,
        # 20% CCF
        "ccf_20": 0.20,
        "trade_lc": 0.20,
        "short_term_trade": 0.20,
        "transaction_related": 0.20,
        # 40% CCF
        "ccf_40": 0.40,
        "committed": 0.40,
        "committed_facility": 0.40,
        "undrawn_committed": 0.40,
        "nif": 0.40,
        "ruf": 0.40,
        # 50% CCF
        "ccf_50": 0.50,
        "performance": 0.50,
        "performance_bond": 0.50,
        "bid_bond": 0.50,
        "warranty": 0.50,
        # 100% CCF
        "ccf_100": 1.00,
        "direct_credit_substitute": 1.00,
        "guarantee": 1.00,
        "standby_lc": 1.00,
        "acceptance": 1.00,
        "forward": 1.00,
    }

    # Try case-insensitive lookup
    category_lower = ccf_category.lower().replace(" ", "_").replace("-", "_")
    if category_lower in category_map:
        return category_map[category_lower]

    # Default to 100% CCF if unknown (conservative approach)
    return 1.00


def calculate_ead_from_contingent(
    nominal_amount: float,
    ccf_category: str,
    drawn_amount: float = 0.0,
) -> dict:
    """
    Calculate EAD for off-balance sheet contingent exposure.

    Args:
        nominal_amount: Nominal/notional amount of commitment
        ccf_category: Category for CCF lookup
        drawn_amount: Already drawn amount (for committed facilities)

    Returns:
        Dictionary with:
        - nominal_amount: Original nominal
        - drawn_amount: Already drawn
        - undrawn_amount: Available but undrawn
        - ccf: Credit Conversion Factor applied
        - ead_undrawn: EAD from undrawn portion
        - ead_drawn: EAD from drawn portion (if any)
        - total_ead: Total EAD

    Formula: EAD = Drawn + (Undrawn × CCF)

    Reference: CRE20.93
    """
    # Get CCF
    ccf = get_ccf(ccf_category)

    # Calculate undrawn amount
    undrawn_amount = max(nominal_amount - drawn_amount, 0.0)

    # Calculate EAD components
    ead_drawn = drawn_amount
    ead_undrawn = undrawn_amount * ccf
    total_ead = ead_drawn + ead_undrawn

    return {
        "nominal_amount": nominal_amount,
        "drawn_amount": drawn_amount,
        "undrawn_amount": undrawn_amount,
        "ccf": ccf,
        "ead_undrawn": ead_undrawn,
        "ead_drawn": ead_drawn,
        "total_ead": total_ead,
    }


def get_ccf_description(ccf_category: str) -> str:
    """
    Get regulatory description for a CCF category.

    Args:
        ccf_category: Category code

    Returns:
        Description string for audit trail
    """
    descriptions = {
        "unconditionally_cancellable": "0% - Unconditionally cancellable commitments (CRE20.94)",
        "retail_unconditionally_cancellable": "10% - Retail unconditionally cancellable (Basel 3.1)",
        "short_term_trade_lc": "20% - Short-term trade LCs (CRE20.95)",
        "transaction_related": "20% - Transaction-related contingencies (CRE20.95)",
        "committed_facility": "40% - Other committed facilities (CRE20.96)",
        "nif_ruf": "40% - Note issuance/revolving underwriting (CRE20.96)",
        "performance_bonds": "50% - Performance-related contingencies (CRE20.97)",
        "bid_bonds": "50% - Bid bonds (CRE20.97)",
        "warranties": "50% - Warranties (CRE20.97)",
        "direct_credit_substitute": "100% - Direct credit substitutes (CRE20.98)",
        "acceptances": "100% - Acceptances (CRE20.98)",
        "forward_purchase": "100% - Forward asset purchases (CRE20.98)",
    }

    return descriptions.get(ccf_category, f"CCF category: {ccf_category}")
