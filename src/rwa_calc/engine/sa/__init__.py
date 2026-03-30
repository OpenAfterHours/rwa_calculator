"""Standardised Approach (SA) calculation components.

Provides:
- SACalculator: Main SA calculator implementing SACalculatorProtocol
- SupportingFactorCalculator: SME/infrastructure factor calculator

Note: These components calculate RWA using Standardised Approach
risk weights per CRR Art. 112-134 and supporting factors per Art. 501.
"""

from rwa_calc.engine.sa.calculator import SACalculator, create_sa_calculator
from rwa_calc.engine.sa.supporting_factors import (
    SupportingFactorCalculator,
    create_supporting_factor_calculator,
)

__all__ = [
    "SACalculator",
    "SupportingFactorCalculator",
    "create_sa_calculator",
    "create_supporting_factor_calculator",
]
