"""
CRR supporting factors never reach an own-funds line (review item CC-08).

Pipeline position:
    calculators -> SupportingFactorCalculator.apply_factors

Key responsibilities under test:
- A settlement-risk (``SETTLEMENT_FAILED_TRADE``) or CCP default-fund
  (``CCR_DEFAULT_FUND``) row keeps a factor of 1.0 even when its counterparty is
  an SME or the row is tagged infrastructure, while an ordinary SME loan on the
  same frame still takes the Art. 501 factor (the control).

Rule text: the row's amount is an own funds requirement — CRR Art. 378 "in order
to calculate the institution's own funds requirement for settlement risk"; CCR
(CRR) Part Art. 308(3) / 309(2) RWEA = own funds x 12.5 — not an exposure "to an
SME" (Art. 501(1)) or to an infrastructure entity (Art. 501a(1)).

Before the fix a synthetic row escaped the factor only because its
``is_defaulted`` was null; with a populated ``is_defaulted = False`` (as here)
it took 0.7619, cutting a 625,000 settlement-risk RWEA to 476,187.50.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator


@pytest.mark.parametrize("risk_type", ["SETTLEMENT_FAILED_TRADE", "CCR_DEFAULT_FUND"])
def test_own_funds_line_takes_no_sme_or_infrastructure_factor(risk_type: str) -> None:
    # Arrange: one SME counterparty, one ordinary loan (control) and one own-funds line.
    exposures = pl.LazyFrame(
        {
            "exposure_reference": ["LOAN", "OWN_FUNDS"],
            "counterparty_reference": ["SME", "SME"],
            "risk_type": [None, risk_type],
            "ead_final": [100_000.0, 50_000.0],
            "drawn_amount": [100_000.0, 50_000.0],
            "interest": [0.0, 0.0],
            "rwa_pre_factor": [100_000.0, 625_000.0],
            "is_sme": [True, True],
            "is_infrastructure": [False, True],
            "is_defaulted": [False, False],
            "is_buy_to_let": [False, False],
            "lending_group_reference": [None, None],
            "cp_annual_revenue": [5_000_000.0, 5_000_000.0],
            "exposure_class": ["corporate_sme", "corporate_sme"],
        },
        schema_overrides={"risk_type": pl.String, "lending_group_reference": pl.String},
    )
    config = CalculationConfig.crr(reporting_date=date(2026, 3, 31))

    # Act
    out = SupportingFactorCalculator().apply_factors(exposures, config).collect()
    factor = dict(zip(out["exposure_reference"], out["supporting_factor"], strict=True))
    rwa = dict(zip(out["exposure_reference"], out["rwa_post_factor"], strict=True))

    # Assert
    assert factor["LOAN"] == pytest.approx(0.7619), "control: the SME loan keeps Art. 501"
    assert factor["OWN_FUNDS"] == 1.0
    assert rwa["OWN_FUNDS"] == pytest.approx(625_000.0)
