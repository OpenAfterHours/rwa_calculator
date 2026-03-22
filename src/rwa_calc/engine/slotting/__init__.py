"""Specialised Lending Slotting approach calculation components.

Provides:
- SlottingCalculator: Main slotting calculator implementing SlottingCalculatorProtocol
- SlottingLazyFrame: Polars namespace for fluent slotting calculations
- SlottingExpr: Polars expression namespace for column-level operations

Supports both CRR and Basel 3.1 frameworks with appropriate risk weights.

Usage with namespace:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.slotting import SlottingLazyFrame  # Registers namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .slotting.prepare_columns(config)
        .slotting.apply_slotting_weights(config)
        .slotting.calculate_rwa()
    )

References:
- CRR Art. 153(5): Supervisory slotting approach
- CRR Art. 147(8): Specialised lending definition
"""

# Import namespace module to register namespaces on module load
import rwa_calc.engine.slotting.namespace  # noqa: F401
from rwa_calc.engine.slotting.calculator import (
    SlottingCalculator,
    create_slotting_calculator,
)
from rwa_calc.engine.slotting.namespace import SlottingExpr, SlottingLazyFrame

__all__ = [
    "SlottingCalculator",
    "create_slotting_calculator",
    # Namespace classes
    "SlottingLazyFrame",
    "SlottingExpr",
]
