"""
UK Credit Risk RWA Calculator.

A high-performance Risk-Weighted Assets (RWA) calculator for UK credit risk,
supporting both CRR (Basel 3.0) and Basel 3.1 (PRA PS9/24) frameworks.

Basic usage:
    >>> from datetime import date
    >>> from rwa_calc.engine.pipeline import create_pipeline
    >>> from rwa_calc.contracts.config import CalculationConfig
    >>>
    >>> config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
    >>> pipeline = create_pipeline()
    >>> result = pipeline.run(config)
"""

__version__ = "0.1.11"
__author__ = "OpenAfterHours"
__license__ = "Apache-2.0"

__all__ = [
    "__version__",
    "__author__",
    "__license__",
]
