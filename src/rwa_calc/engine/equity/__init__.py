"""Equity exposure calculation components.

Provides:
- EquityCalculator: Main equity calculator implementing EquityCalculatorProtocol
- EquityLazyFrame: Polars namespace for fluent equity calculations
- EquityExpr: Polars expression namespace for column-level operations

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

Usage with namespace:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.equity import EquityLazyFrame  # Registers namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .equity.prepare_columns(config)
        .equity.apply_equity_weights_sa()
        .equity.calculate_rwa()
    )

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- EBA Q&A 2023_6716: Strategic equity treatment
"""

# Import namespace module to register namespaces on module load
import rwa_calc.engine.equity.namespace  # noqa: F401
from rwa_calc.engine.equity.calculator import (
    EquityCalculator,
    create_equity_calculator,
)
from rwa_calc.engine.equity.namespace import EquityExpr, EquityLazyFrame

__all__ = [
    "EquityCalculator",
    "create_equity_calculator",
    # Namespace classes
    "EquityLazyFrame",
    "EquityExpr",
]
