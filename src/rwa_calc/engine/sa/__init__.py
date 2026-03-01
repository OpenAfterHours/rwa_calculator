"""Standardised Approach (SA) calculation components.

Provides:
- SACalculator: Main SA calculator implementing SACalculatorProtocol
- SupportingFactorCalculator: SME/infrastructure factor calculator
- SALazyFrame: Polars namespace for fluent SA calculations
- SAExpr: Polars expression namespace for column-level operations

Note: These components calculate RWA using Standardised Approach
risk weights per CRR Art. 112-134 and supporting factors per Art. 501.

Usage with namespace:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.sa import SALazyFrame  # Registers namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .sa.prepare_columns(config)
        .sa.apply_risk_weights(config)
        .sa.calculate_rwa()
        .sa.apply_supporting_factors(config)
    )
"""

# Import namespace module to register namespaces on module load
import rwa_calc.engine.sa.namespace  # noqa: F401
from rwa_calc.engine.sa.calculator import SACalculator, create_sa_calculator
from rwa_calc.engine.sa.namespace import SAExpr, SALazyFrame
from rwa_calc.engine.sa.supporting_factors import (
    SupportingFactorCalculator,
    create_supporting_factor_calculator,
)

__all__ = [
    "SACalculator",
    "SupportingFactorCalculator",
    "create_sa_calculator",
    "create_supporting_factor_calculator",
    # Namespace classes
    "SALazyFrame",
    "SAExpr",
]
