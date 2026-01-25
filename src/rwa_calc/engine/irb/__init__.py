"""IRB (Internal Ratings-Based) approach calculation components.

Provides:
- IRBCalculator: Main IRB calculator implementing IRBCalculatorProtocol
- IRB formulas: K formula, correlation, maturity adjustment
- IRBLazyFrame: Polars namespace for fluent IRB calculations
- IRBExpr: Polars expression namespace for column-level operations

Supports both F-IRB (supervisory LGD) and A-IRB (own LGD estimates).

Usage with namespace:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.irb import IRBLazyFrame  # Registers namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .irb.classify_approach(config)
        .irb.apply_firb_lgd(config)
        .irb.prepare_columns(config)
        .irb.apply_all_formulas(config)
    )

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

# Import namespace module to register namespaces on module load
import rwa_calc.engine.irb.namespace  # noqa: F401

from rwa_calc.engine.irb.calculator import IRBCalculator, create_irb_calculator
from rwa_calc.engine.irb.formulas import (
    apply_irb_formulas,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
)
from rwa_calc.engine.irb.namespace import IRBExpr, IRBLazyFrame
from rwa_calc.engine.irb.stats_backend import get_backend

__all__ = [
    "IRBCalculator",
    "create_irb_calculator",
    "calculate_correlation",
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_irb_rwa",
    "calculate_expected_loss",
    "apply_irb_formulas",
    # Namespace classes
    "IRBLazyFrame",
    "IRBExpr",
    # Backend diagnostics
    "get_backend",
]
