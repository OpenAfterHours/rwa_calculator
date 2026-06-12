"""Specialised Lending Slotting approach calculation components.

Provides:
- SlottingCalculator: Main slotting calculator implementing SlottingCalculatorProtocol

Supports both CRR and Basel 3.1 frameworks with appropriate risk weights.
The calculation steps are plain typed functions in the sibling ``transforms``
module, composed via ``LazyFrame.pipe``.

References:
- CRR Art. 153(5): Supervisory slotting approach
- CRR Art. 147(8): Specialised lending definition
"""

from rwa_calc.engine.slotting.calculator import (
    SlottingCalculator,
    create_slotting_calculator,
)

__all__ = [
    "SlottingCalculator",
    "create_slotting_calculator",
]
