"""Credit Risk Mitigation processing components.

Provides:
- CRMProcessor: Main CRM processor for all CRM techniques
- HaircutCalculator: Collateral haircuts

Note: CCF (Credit Conversion Factors) is in engine/ccf.py as it's
part of exposure measurement, not credit risk mitigation.
"""

from rwa_calc.engine.crm.haircuts import HaircutCalculator, create_haircut_calculator
from rwa_calc.engine.crm.processor import CRMProcessor, create_crm_processor

__all__ = [
    "CRMProcessor",
    "HaircutCalculator",
    "create_crm_processor",
    "create_haircut_calculator",
]
