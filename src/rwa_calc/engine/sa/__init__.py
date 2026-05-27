"""Standardised Approach (SA) calculation components.

Provides:
- SACalculator: Main SA calculator implementing SACalculatorProtocol
- lf.sa.* fluent Polars namespace (registered via the ``namespace`` module)

Note: These components calculate RWA using Standardised Approach
risk weights per CRR Art. 112-134. Supporting factors (CRR Art. 501 / 501a)
are cross-approach and live in ``rwa_calc.engine.supporting_factors``.
"""

# Import ``namespace`` first so the ``lf.sa`` Polars namespace is registered
# before any caller uses it on a LazyFrame.
from rwa_calc.engine.sa import namespace as _namespace  # noqa: F401
from rwa_calc.engine.sa.calculator import SACalculator, create_sa_calculator

__all__ = [
    "SACalculator",
    "create_sa_calculator",
]
