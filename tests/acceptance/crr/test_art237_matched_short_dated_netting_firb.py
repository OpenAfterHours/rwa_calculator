"""
CRR — a matched short-dated interbank pair nets in full under F-IRB (Art. 219/237).

The 2026-09-05 escape: an F-IRB institution loan fully offset by a same-currency,
same-maturity deposit under one netting agreement reported LGD 45% and full RWA
because the maturity-mismatch step floored the exposure residual at 0.25 years
before comparing it with the deposit's, fabricating a mismatch for every matched
pair inside three months of the reporting date.

    matched_7d / 60d / 89d — inside the window → LGD* 0, RW 0, RWA 0
    matched_past           — contractual date already passed → LGD* 0, RWA 0
    matched_6m             — control outside the window → LGD* 0, RWA 0
    mismatch_30d_vs_2y     — control: a REAL sub-three-month mismatch still zeroes
                             the protection → LGD* 45%, RWA > 0

References:
    - CRR Art. 219: on-B/S netting treated as cash collateral.
    - CRR Art. 237(1): a mismatch exists only where protection is SHORTER than the
      exposure; sub-three-month protection is ineligible only then.
    - CRR Art. 238(1): exposure maturity capped at five years, not floored.
    - CRR Art. 161(1)(a): 45% senior unsecured F-IRB LGD.
    - docs/development/escape-log.md: 2026-09-05 matched short-dated pair.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.matched_short_netting.matched_short_netting import (
    LOAN_DRAWN,
    SCENARIOS,
    build_matched_short_netting_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_MATURITY_MISMATCH
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2025, 12, 31)
SENIOR_UNSECURED_LGD = 0.45


def _run(label: str):
    bundle = build_matched_short_netting_bundle([label], REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE, permission_mode=PermissionMode.IRB
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_row(result, loan_ref: str) -> dict:
    df = result.results.collect().filter(pl.col("exposure_reference") == loan_ref)
    assert df.height == 1, f"expected one result row for {loan_ref}, got {df.height}"
    return df.to_dicts()[0]


class TestMatchedShortDatedNettingFirb:
    """Equal residual maturities are never a mismatch, whatever the tenor."""

    @pytest.mark.parametrize("label", ["matched_7d", "matched_60d", "matched_89d"])
    def test_matched_pair_inside_three_months_nets_in_full(self, label: str) -> None:
        s = SCENARIOS[label]
        row = _loan_row(_run(label), s.loan_ref)

        assert row["approach_applied"] == "foundation_irb"
        assert row["on_bs_netting_amount"] == pytest.approx(LOAN_DRAWN)
        assert row["total_collateral_for_lgd"] == pytest.approx(LOAN_DRAWN)
        assert row["lgd_floored"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0, abs=1e-6)

    def test_matched_past_dated_pair_nets_in_full(self) -> None:
        s = SCENARIOS["matched_past"]
        row = _loan_row(_run("matched_past"), s.loan_ref)

        assert row["total_collateral_for_lgd"] == pytest.approx(LOAN_DRAWN)
        assert row["lgd_floored"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0, abs=1e-6)

    def test_matched_six_month_pair_is_the_control(self) -> None:
        s = SCENARIOS["matched_6m"]
        row = _loan_row(_run("matched_6m"), s.loan_ref)

        assert row["lgd_floored"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0, abs=1e-6)

    def test_real_sub_three_month_mismatch_still_zeroes_protection(self) -> None:
        """LOAD-BEARING for the fix: the Art. 237(1) gate must survive it."""
        s = SCENARIOS["mismatch_30d_vs_2y"]
        result = _run("mismatch_30d_vs_2y")
        row = _loan_row(result, s.loan_ref)

        assert row["on_bs_netting_amount"] == pytest.approx(LOAN_DRAWN)
        assert row["total_collateral_for_lgd"] == pytest.approx(0.0)
        assert row["lgd_floored"] == pytest.approx(SENIOR_UNSECURED_LGD)
        assert row["rwa_final"] > 0.0
        # ...and it is no longer silent.
        assert any(e.code == ERROR_MATURITY_MISMATCH for e in result.errors)

    def test_matched_pair_raises_no_maturity_warning(self) -> None:
        result = _run("matched_60d")
        assert not any(e.code == ERROR_MATURITY_MISMATCH for e in result.errors)
