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
