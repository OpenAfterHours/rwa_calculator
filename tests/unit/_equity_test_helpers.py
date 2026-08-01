"""
Shared test helper for Basel 3.1 SA equity risk-weight assignment.

Builds a single-row 11-column equity LazyFrame and calls
EquityCalculator._apply_b31_equity_weights_sa directly, returning the
assigned risk weight. Used by the B31 equity weight and subordinated-debt
unit test modules to exercise weight assignment in isolation (before the
transitional floor is applied).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity import EquityCalculator


def apply_b31_equity_weight_sa(equity_type: str, **kwargs: bool | str | float | None) -> float:
    """Apply B31 SA weight to a single exposure and return the risk_weight."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2031, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    calculator = EquityCalculator()
    df = pl.DataFrame(
        {
            "exposure_reference": ["EQ_TEST"],
            "ead_final": [1_000_000.0],
            "equity_type": [equity_type],
            "is_speculative": [kwargs.get("is_speculative", False)],
            "is_exchange_traded": [kwargs.get("is_exchange_traded", False)],
            "is_government_supported": [kwargs.get("is_government_supported", False)],
            "is_diversified_portfolio": [False],
            "ciu_approach": [kwargs.get("ciu_approach")],
            "ciu_mandate_rw": [kwargs.get("ciu_mandate_rw")],
            "ciu_third_party_calc": [kwargs.get("ciu_third_party_calc")],
            "ciu_look_through_rw": [None],
            # Art. 132(4) unrestricted-access derogation (P1.258). This helper
            # calls the weight functions directly, bypassing the equity input
            # contract, so every column the expressions read must be present here.
            "ciu_unrestricted_access": [kwargs.get("ciu_unrestricted_access")],
        }
    ).lazy()
    result = calculator._apply_b31_equity_weights_sa(df, config).collect()
    return result["risk_weight"][0]
