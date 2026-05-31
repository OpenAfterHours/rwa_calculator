"""
P1.190 Basel 3.1 — F-IRB Foundation Collateral Method (Art. 230): b31_re_threshold_30pct.

Scenario: £3m RRE collateral against £10m senior corporate exposure.
Coverage is exactly 30% of EAD — the boundary where CRR's C* threshold would apply.
Under CRR, C* = 30% of EAD means collateral at exactly the threshold is included;
only sub-threshold collateral is zeroed. Under Basel 3.1 no such threshold exists.

This scenario verifies that the B31 path correctly processes collateral at the 30%
EAD boundary and produces the expected LGD* from Art. 230(1).

Hand-calculation (PS1/26 Art. 230(1), LGDU=40%, LGDS=20%, HC=40%):
    EAD                  = 10,000,000.00
    MV                   = 3,000,000.00
    HC                   = 0.40  (Art. 230(2) immovable property)
    Hfx                  = 0.00  (GBP/GBP)
    C_adjusted           = 3,000,000 × (1 - 0.40 - 0.00) = 1,800,000.00
    OC_ratio             = 1.0   (B31: no divisor for non-financial)
    ES                   = min(1,800,000 / 1.0, 10,000,000) = 1,800,000.00
    secured_fraction     = 1,800,000 / 10,000,000 = 0.18
    unsecured_fraction   = 1 - 0.18 = 0.82
    LGD*                 = 0.40 × 0.82 + 0.20 × 0.18
                         = 0.3280 + 0.0360
                         = 0.3640

Expected:  lgd_floored == 0.3640 ± 1e-3

References:
    - PRA PS1/26 Art. 230(1): LGD* continuous formula (no C* threshold)
    - PRA PS1/26 Art. 230(2): HC table (40% immovable property), LGDS (20% RE)
    - PRA PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%
    - CRR Art. 230(2): C* = 30% of E (CRR only — no equivalent in PS1/26)
    - IMPLEMENTATION_PLAN.md: P1.190 — b31_re_threshold_30pct scenario
"""

from __future__ import annotations

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import build_p1_190_bundle, find_loan_rows, first
from tests.fixtures.p1_190.p1_190 import (
    B31_RE_THRESHOLD_CP_REF,
    B31_RE_THRESHOLD_EXPECTED_LGD_STAR,
    B31_RE_THRESHOLD_FAC_REF,
    B31_RE_THRESHOLD_LOAN_REF,
    B31_RE_THRESHOLD_MODEL_ID,
    REPORTING_DATE,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_SCENARIO = "b31_re_threshold_30pct"

# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _run_pipeline() -> object:
    """Run Basel 3.1 F-IRB pipeline for the b31_re_threshold_30pct scenario."""
    bundle = build_p1_190_bundle(_SCENARIO, B31_RE_THRESHOLD_FAC_REF, B31_RE_THRESHOLD_LOAN_REF)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestP1190B31ReThreshold30Pct:
    """
    P1.190 Basel 3.1 b31_re_threshold_30pct: RE collateral at CRR C* boundary.

    load-bearing: lgd_floored == 0.3640 ± 1e-3
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        """Run Basel 3.1 F-IRB pipeline for b31_re_threshold_30pct and cache."""
        return _run_pipeline()

    @pytest.fixture(scope="class")
    def loan_rows(self, pipeline_result) -> list[dict]:
        """All result rows for the threshold-RE loan."""
        rows = find_loan_rows(pipeline_result, B31_RE_THRESHOLD_LOAN_REF)
        assert rows, (
            f"P1.190 b31_re_threshold_30pct: no pipeline result rows for "
            f"loan_ref='{B31_RE_THRESHOLD_LOAN_REF}'. "
            f"Counterparty {B31_RE_THRESHOLD_CP_REF} must be routed to F-IRB via "
            f"model_id='{B31_RE_THRESHOLD_MODEL_ID}'."
        )
        return rows

    def test_p1_190_b31_re_threshold_irb_routed(self, loan_rows: list[dict]) -> None:
        """
        P1.190 b31_re_threshold_30pct: confirm F-IRB routing — pd_floored must be present.

        Arrange: Basel 3.1 pipeline, b31_re_threshold_30pct scenario.
        Act:     inspect pipeline result rows for B31_RE_THRESHOLD_LOAN_REF.
        Assert:  pd_floored is not None.
        """
        pd_floored = first(loan_rows, "pd_floored")
        assert pd_floored is not None, (
            f"P1.190 b31_re_threshold_30pct: pd_floored not found — loan may have fallen "
            f"back to SA. Check model_permission_{_SCENARIO}.parquet."
        )

    def test_p1_190_b31_re_threshold_lgd_star_expected(self, loan_rows: list[dict]) -> None:
        """
        P1.190 b31_re_threshold_30pct LOAD-BEARING: lgd_floored == 0.3640 ± 1e-3.

        The MV=£3m is exactly at 30% of £10m EAD (the CRR C* boundary).
        Under Basel 3.1 there is no C* threshold — collateral is fully recognised.

        After bug (a) fix (no C* under B31), and bugs (b)+(c) fix (HC=40%, OC=1.0):
          C_adjusted = 3m × 0.60 = 1.8m
          ES = 1.8m / 1.0 = 1.8m
          LGD* = 0.40 × 0.82 + 0.20 × 0.18 = 0.3640

        Pre-fix (bug a: C* gate treats 30% as the threshold boundary; with bugs b+c):
          result may differ depending on how engine handles the exact boundary.

        Arrange: Basel 3.1 F-IRB, b31_re_threshold_30pct, MV=£3m, EAD=£10m.
        Act:     full pipeline.
        Assert:  lgd_floored == 0.3640 ± 1e-3.

        Pre-fix: different value → AssertionError.
        """
        lgd_floored = first(loan_rows, "lgd_floored")

        assert lgd_floored is not None, (
            f"P1.190 b31_re_threshold_30pct: lgd_floored not in result rows for "
            f"'{B31_RE_THRESHOLD_LOAN_REF}'."
        )

        assert lgd_floored == pytest.approx(B31_RE_THRESHOLD_EXPECTED_LGD_STAR, abs=1e-3), (
            f"P1.190 b31_re_threshold_30pct: expected lgd_floored="
            f"{B31_RE_THRESHOLD_EXPECTED_LGD_STAR:.4f} "
            f"(PS1/26 Art. 230: HC=40%, OC=1.0, ES=1.8m, "
            f"0.40×0.82 + 0.20×0.18). "
            f"Got {lgd_floored:.6f}. "
            f"Check that bugs (a), (b), and (c) are all fixed for Basel 3.1."
        )
