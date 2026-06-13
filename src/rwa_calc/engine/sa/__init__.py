"""Standardised Approach (SA) calculation components.

Provides:
- SACalculator: Main SA calculator implementing SACalculatorProtocol
- Plain typed SA transforms in the sibling ``risk_weights`` /
  ``rw_adjustments`` / ``factors_output`` modules, composed via
  ``LazyFrame.pipe``

Note: These components calculate RWA using Standardised Approach
risk weights per CRR Art. 112-134. Supporting factors (CRR Art. 501 / 501a)
are cross-approach and live in ``rwa_calc.engine.supporting_factors``.
"""

from rwa_calc.engine.sa.calculator import SACalculator, create_sa_calculator

__all__ = [
    "SACalculator",
    "create_sa_calculator",
]
