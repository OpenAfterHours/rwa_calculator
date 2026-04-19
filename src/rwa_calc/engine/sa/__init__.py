"""Standardised Approach (SA) calculation components.

Provides:
- SACalculator: Main SA calculator implementing SACalculatorProtocol
- SupportingFactorCalculator: SME/infrastructure factor calculator
- lf.sa.* fluent Polars namespace (registered via the ``namespace`` module)

Note: These components calculate RWA using Standardised Approach
risk weights per CRR Art. 112-134 and supporting factors per Art. 501.
"""

# Import ``namespace`` first so the ``lf.sa`` Polars namespace is registered
# before any caller uses it on a LazyFrame.
from rwa_calc.engine.sa import namespace as _namespace  # noqa: F401
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
