"""Credit Risk Mitigation processing components.

Provides:
- CRMProcessor: Main CRM processor for all CRM techniques
- HaircutCalculator: Collateral haircuts
- CRMLazyFrame: Polars namespace for fluent CRM calculations

Note: CCF (Credit Conversion Factors) is in engine/ccf.py as it's
part of exposure measurement, not credit risk mitigation.

Usage with namespace:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.crm import CRMLazyFrame  # Registers namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (exposures
        .crm.initialize_ead_waterfall()
        .crm.apply_collateral(collateral, config)
        .crm.finalize_ead()
    )
"""

# Import namespace modules to register namespaces on module load
import rwa_calc.engine.crm.haircuts_namespace  # noqa: F401
import rwa_calc.engine.crm.namespace  # noqa: F401
from rwa_calc.engine.crm.haircuts import HaircutCalculator, create_haircut_calculator
from rwa_calc.engine.crm.haircuts_namespace import HaircutsExpr, HaircutsLazyFrame
from rwa_calc.engine.crm.namespace import CRMLazyFrame
from rwa_calc.engine.crm.processor import CRMProcessor, create_crm_processor

__all__ = [
    "CRMProcessor",
    "HaircutCalculator",
    "CRMLazyFrame",
    "HaircutsLazyFrame",
    "HaircutsExpr",
    "create_crm_processor",
    "create_haircut_calculator",
]
