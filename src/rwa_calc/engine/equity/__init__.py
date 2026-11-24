"""Equity exposure calculation components.

Provides:
- EquityCalculator: Main equity calculator implementing EquityCalculatorProtocol

Supports, under CRR, the Article 133 Standardised Approach (the default for SA
firms) and the Article 155 IRB simple risk weight method (for firms with IRB
permission); under Basel 3.1, Article 133 only (PS1/26 removes IRB equity), with
the General Provisions rules 4.1-4.3 transitional weights in 2027-2029. The
weights themselves are rulepack entries (``equity_sa_risk_weights`` and its
siblings in ``rulebook/packs``) and the regime-specific chains live in
``calculator.py``; this docstring states none, so it cannot drift from them.

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
