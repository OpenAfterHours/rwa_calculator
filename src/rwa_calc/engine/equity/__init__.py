"""Equity exposure calculation components.

Provides:
- EquityCalculator: Main equity calculator implementing EquityCalculatorProtocol

Supports two approaches under CRR:
- Article 133: Standardised Approach (SA) - Default for SA firms
- Article 155: IRB Simple Risk Weight Method - For firms with IRB permission

Risk Weight Summary:

Article 133 (SA):
- Central bank: 0%
- Listed/Exchange-traded/Government-supported: 100%
- Unlisted: 250%
- Speculative: 400%

Article 155 (IRB Simple):
- Private equity (diversified portfolio): 190%
- Exchange-traded: 290%
- Other equity: 370%

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- EBA Q&A 2023_6716: Strategic equity treatment
"""

from rwa_calc.engine.equity.calculator import (
    EquityCalculator,
    create_equity_calculator,
)

__all__ = [
    "EquityCalculator",
    "create_equity_calculator",
]
