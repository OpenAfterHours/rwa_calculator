"""
Shared components for CRR and Basel 3.1 workbooks.

This module contains framework-independent code that is used by both
the CRR (Basel 3.0) and Basel 3.1 expected outputs workbooks.
"""

from workbooks.shared.correlation import calculate_correlation
from workbooks.shared.fixture_loader import FixtureData, load_fixtures, load_fixtures_eager
from workbooks.shared.irb_formulas import (
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
)

__all__ = [
    "FixtureData",
    "load_fixtures",
    "load_fixtures_eager",
    "calculate_irb_rwa",
    "calculate_k",
    "calculate_maturity_adjustment",
    "calculate_expected_loss",
    "calculate_correlation",
]
