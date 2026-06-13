"""IRB (Internal Ratings-Based) approach calculation components.

Provides:
- IRBCalculator: Main IRB calculator implementing IRBCalculatorProtocol
- IRB formulas: K formula, correlation, maturity adjustment
- Plain typed IRB transforms in the sibling ``transforms`` module,
  composed via ``LazyFrame.pipe``

Supports both F-IRB (supervisory LGD) and A-IRB (own LGD estimates).

Usage with transforms:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.irb.transforms import (
        apply_all_formulas,
        apply_firb_lgd,
        classify_approach,
        prepare_columns,
    )

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (
        lf.pipe(classify_approach, config)
        .pipe(apply_firb_lgd, config)
        .pipe(prepare_columns, config)
        .pipe(apply_all_formulas, config)
    )

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

from rwa_calc.engine.irb.calculator import IRBCalculator, create_irb_calculator
from rwa_calc.engine.irb.formulas import (
    apply_irb_formulas,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
)

__all__ = [
    "IRBCalculator",
    "create_irb_calculator",
    "calculate_correlation",
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_irb_rwa",
    "calculate_expected_loss",
    "apply_irb_formulas",
]
