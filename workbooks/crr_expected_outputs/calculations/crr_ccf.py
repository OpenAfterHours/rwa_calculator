"""
CRR Credit Conversion Factors (CRR Art. 111).

Implements CCF lookups for off-balance sheet items.
"""

from decimal import Decimal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.crr_expected_outputs.data.crr_params import CRR_CCF


def get_ccf(commitment_type: str, original_maturity_years: float | None = None) -> Decimal:
    """
    Get CCF for off-balance sheet item (CRR Art. 111).

    Args:
        commitment_type: Type of commitment/contingent
        original_maturity_years: Original maturity (for commitments)

    Returns:
        CCF as Decimal

    CRR CCF Categories:
    - 0% (Low risk): Unconditionally cancellable
    - 20% (Medium-low): Short-term trade LCs, undrawn <= 1 year
    - 50% (Medium): Undrawn > 1 year, performance guarantees, NIFs/RUFs
    - 100% (Full): Guarantees, acceptances, credit derivatives
    """
    # Direct lookup for known types
    if commitment_type in CRR_CCF:
        return CRR_CCF[commitment_type]

    # Map common types to CCF categories
    type_mapping = {
        # 0% CCF
        "unconditionally_cancellable": "low_risk",
        "revocable": "low_risk",
        # 20% CCF
        "documentary_lc": "documentary_credit",
        "short_term_lc": "short_term_lc",
        "trade_lc": "documentary_credit",
        "undrawn_revolver_short": "undrawn_short_term",
        # 50% CCF
        "undrawn_revolver_long": "undrawn_long_term",
        "committed_undrawn": "undrawn_long_term",
        "rcf_undrawn": "undrawn_long_term",
        "performance_bond": "performance_guarantee",
        "bid_bond": "bid_bond",
        "warranty": "performance_guarantee",
        "nif": "nif_ruf",
        "ruf": "nif_ruf",
        "standby_letter_of_credit": "standby_lc",
        # 100% CCF
        "guarantee": "guarantee_given",
        "financial_guarantee": "guarantee_given",
        "acceptance": "acceptance",
        "credit_derivative": "credit_derivative",
        "forward_asset_purchase": "forward_purchase",
    }

    mapped_type = type_mapping.get(commitment_type.lower())
    if mapped_type and mapped_type in CRR_CCF:
        return CRR_CCF[mapped_type]

    # If maturity provided, use that to determine CCF for undrawn facilities
    if original_maturity_years is not None:
        if original_maturity_years <= 1:
            return CRR_CCF["undrawn_short_term"]
        else:
            return CRR_CCF["undrawn_long_term"]

    # Default to medium risk (50%)
    return CRR_CCF["medium_risk"]


def calculate_ead_off_balance_sheet(
    nominal_amount: Decimal, commitment_type: str, original_maturity_years: float | None = None
) -> tuple[Decimal, Decimal, str]:
    """
    Calculate EAD for off-balance sheet item (CRR Art. 111).

    Args:
        nominal_amount: Nominal/notional amount
        commitment_type: Type of commitment
        original_maturity_years: Original maturity

    Returns:
        Tuple of (ead, ccf, description)
    """
    ccf = get_ccf(commitment_type, original_maturity_years)
    ead = nominal_amount * ccf

    return ead, ccf, f"EAD = {nominal_amount:,.0f} × {ccf:.0%} = {ead:,.0f}"
