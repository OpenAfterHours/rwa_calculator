"""
Basel 3.1 — a matched short-dated interbank pair nets in full under F-IRB.

Regime twin of the CRR scenario. PS1/26 carries Art. 219 and Art. 237-239
forward unchanged in substance, so a same-currency, same-maturity deposit must
net an F-IRB institution loan in full at any tenor; only a REAL sub-three-month
mismatch zeroes the protection. The FSE institution takes the PS1/26
Art. 161(1)(a) 45% senior unsecured LGD when nothing nets.

References:
    - PS1/26 Art. 219(1)/(3): netting as cash collateral; mismatch via Art. 239(2).
    - PS1/26 Art. 237(1), 238(1): mismatch definition and the five-year cap.
    - PS1/26 Art. 161(1)(a): 45% FSE senior unsecured F-IRB LGD.
    - docs/development/escape-log.md: 2026-09-05 matched short-dated pair.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_MATURITY_MISMATCH
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.matched_short_netting.matched_short_netting import (
    LOAN_DRAWN,
    SCENARIOS,
    build_matched_short_netting_bundle,
)

REPORTING_DATE = date(2027, 6, 30)
FSE_SENIOR_UNSECURED_LGD = 0.45


def _run(label: str):
    bundle = build_matched_short_netting_bundle([label], REPORTING_DATE)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_row(result, loan_ref: str) -> dict:
    df = result.results.collect().filter(pl.col("exposure_reference") == loan_ref)
    assert df.height == 1, f"expected one result row for {loan_ref}, got {df.height}"
    return df.to_dicts()[0]


class TestMatchedShortDatedNettingFirbB31:
    """Equal residual maturities are never a mismatch under PS1/26 either."""

    @pytest.mark.parametrize("label", ["matched_7d", "matched_60d", "matched_89d"])
    def test_matched_pair_inside_three_months_nets_in_full(self, label: str) -> None:
        s = SCENARIOS[label]
        row = _loan_row(_run(label), s.loan_ref)

        assert row["approach_applied"] == "foundation_irb"
        assert row["on_bs_netting_amount"] == pytest.approx(LOAN_DRAWN)
        assert row["total_collateral_for_lgd"] == pytest.approx(LOAN_DRAWN)
        assert row["lgd_floored"] == pytest.approx(0.0)
        assert row["rwa_pre_floor"] == pytest.approx(0.0, abs=1e-6)

    def test_matched_past_dated_pair_nets_in_full(self) -> None:
        s = SCENARIOS["matched_past"]
        row = _loan_row(_run("matched_past"), s.loan_ref)

        assert row["total_collateral_for_lgd"] == pytest.approx(LOAN_DRAWN)
        assert row["lgd_floored"] == pytest.approx(0.0)
        assert row["rwa_pre_floor"] == pytest.approx(0.0, abs=1e-6)

    def test_real_sub_three_month_mismatch_still_zeroes_protection(self) -> None:
        s = SCENARIOS["mismatch_30d_vs_2y"]
        result = _run("mismatch_30d_vs_2y")
        row = _loan_row(result, s.loan_ref)

        assert row["total_collateral_for_lgd"] == pytest.approx(0.0)
        assert row["lgd_floored"] == pytest.approx(FSE_SENIOR_UNSECURED_LGD)
        assert row["rwa_pre_floor"] > 0.0
        assert any(e.code == ERROR_MATURITY_MISMATCH for e in result.errors)
