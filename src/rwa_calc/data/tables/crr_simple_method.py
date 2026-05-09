"""
Financial Collateral Simple Method regulatory constants (CRR Art. 222).

Pipeline position:
    Data Tables -> CRMProcessor (FCSM branch) -> SACalculator

Key responsibilities:
- Hold the SA risk-weight floor and sovereign-bond market-value discount
  used by the Financial Collateral Simple Method
- Both retained unchanged under PRA PS1/26 (Basel 3.1 keeps Art. 222 for
  SA exposures), so no separate B31 variants are required

References:
- CRR Art. 222(1): minimum 20% RW floor for the secured portion
- CRR Art. 222(4)(b): 20% market-value discount for 0%-RW sovereign bonds
- PRA PS1/26 Art. 222: Retained for SA exposures under Basel 3.1
"""

from __future__ import annotations

from decimal import Decimal

# Art. 222(1): minimum 20% RW floor for the secured portion (general case)
FCSM_RW_FLOOR: Decimal = Decimal("0.20")

# Art. 222(4)(b): 20% market-value discount applied to 0%-RW sovereign bonds
# eligible for the same-currency 0% RW exception
SOVEREIGN_BOND_DISCOUNT: Decimal = Decimal("0.20")

# PRA PS1/26 Art. 222(4) / CRR Art. 222(4): SFT carve-out — when an SFT exposure
# is collateralised by financial collateral that meets the Art. 227(2)
# zero-haircut criteria, the secured-portion RW floor is replaced as follows:
#   (a) Counterparty is a "core market participant" (Art. 227(3)) → 0% floor
#   (b) Otherwise                                                  → 10% floor
ART_222_4_CMP_RW: Decimal = Decimal("0.00")
ART_222_4_NON_CMP_RW: Decimal = Decimal("0.10")

# FCSM Art. 222(1): the SA RW prescribed for the type of collateral.
# Equity instruments held as collateral are treated at 100% under both CRR
# Art. 133(2) (uniform 100%) and PRA PS1/26 Art. 222(1) (FCSM applies the
# financial-instrument character of the equity, not the equity-exposure
# character that would attract Art. 133(3)'s 250% under B31).
FCSM_EQUITY_COLLATERAL_RW: Decimal = Decimal("1.00")
