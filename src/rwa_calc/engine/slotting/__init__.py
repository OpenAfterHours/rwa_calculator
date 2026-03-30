"""Specialised Lending Slotting approach calculation components.

Provides:
- SlottingCalculator: Main slotting calculator implementing SlottingCalculatorProtocol

Supports both CRR and Basel 3.1 frameworks with appropriate risk weights.
Polars namespaces (``lf.slotting.*``) are registered on import.

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

__all__ = [
    "SlottingCalculator",
    "create_slotting_calculator",
]
