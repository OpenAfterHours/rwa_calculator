"""
P2.17: CRR Art. 123 second subparagraph — payroll/pension loan 35% risk weight.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate that retail loans with is_payroll_loan=True receive a 35% SA risk weight
  under CRR Art. 123 second subparagraph (inserted by CRR2, Regulation (EU) 2019/876 F68).
- Validate that standard retail loans (is_payroll_loan=False) continue to receive the
  standard 75% risk weight under CRR Art. 123 first paragraph.
- Anti-regression guard: payroll loans must not silently revert to 75% if a future
  refactor removes the is_payroll_loan check.

Bug (pre-fix):
    The CRR SA engine's retail branch applies 75% flat to all retail exposures and does
    not check is_payroll_loan. The is_payroll_loan=True flag on LOAN_PAY_001 and
    LOAN_PAY_002 is ignored, causing both to receive 75% instead of 35%.

Hand-calculations (CRR, CalculationConfig.crr(), base_currency="GBP"):

  LOAN_PAY_001 (CP_RETAIL_PAY_001, is_payroll_loan=True):
    Exposure class: RETAIL_OTHER
    EAD = drawn_amount = 50,000
    SA RW (Art. 123 second subparagraph): 35%
    RWA = 50,000 × 0.35 = 17,500

  LOAN_PAY_002 (CP_RETAIL_PAY_002, is_payroll_loan=True):
    Exposure class: RETAIL_OTHER
    EAD = drawn_amount = 25,000
    SA RW (Art. 123 second subparagraph): 35%
    RWA = 25,000 × 0.35 = 8,750

  LOAN_NONPAY_003 (CP_RETAIL_NONPAY_003, is_payroll_loan=False):
    Exposure class: RETAIL_OTHER
    EAD = drawn_amount = 30,000
    SA RW (Art. 123 first paragraph): 75%
    RWA = 30,000 × 0.75 = 22,500

Pre-fix failure mode:
    LOAN_PAY_001: risk_weight = 0.75 (wrong), should be 0.35
    LOAN_PAY_002: risk_weight = 0.75 (wrong), should be 0.35
    LOAN_NONPAY_003: risk_weight = 0.75 (correct — control row)

References:
    - CRR Art. 123 second subparagraph (CRR2, Regulation (EU) 2019/876 F68):
      payroll/pension loan 35% RW conditions (a)-(d)
    - src/rwa_calc/engine/sa/namespace.py: CRR retail branch (missing payroll check)
    - tests/fixtures/p2_17/p2_17.py: scenario constants and bundle builder
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_17"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth from the fixture builder)
# ---------------------------------------------------------------------------

from tests.fixtures.p2_17.p2_17 import (  # noqa: E402
    EXPECTED_RW_PAYROLL,
    EXPECTED_RW_RETAIL,
    EXPECTED_RWA_NONPAY_003,
    EXPECTED_RWA_PAY_001,
    EXPECTED_RWA_PAY_002,
    LOAN_NONPAY_003,
    LOAN_PAY_001,
    LOAN_PAY_002,
    build_p2_17_bundle,
)

# Tolerances
_RW_TOL = 1e-9   # absolute on risk_weight (exact scalar lookup — no float arithmetic)
_RWA_TOL = 0.01  # £0.01 absolute on rwa_final


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_17_crr_results() -> dict[str, dict]:
    """
    Run the P2.17 fixtures through the CRR SA pipeline once.

    Returns a mapping of loan_reference -> result row dict for all three loans.
    Module-scoped to avoid repeated pipeline runs.

    Pre-fix: LOAN_PAY_001 and LOAN_PAY_002 receive risk_weight=0.75 (flat retail,
    engine ignores is_payroll_loan flag).
    Post-fix: LOAN_PAY_001 and LOAN_PAY_002 must receive risk_weight=0.35
    (CRR Art. 123 second subparagraph).

    LOAN_NONPAY_003 is a control row — it must remain at 0.75 in both pre- and
    post-fix states.
    """
    # Arrange
    bundle = build_p2_17_bundle(fixtures_dir=_FIXTURES_DIR)
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30),
        base_currency="GBP",
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P2.17 CRR: SA results should not be None for SA-only standardised config"
    )

    df = results.sa_results.collect()

    rows: dict[str, dict] = {}
    for loan_ref in (LOAN_PAY_001, LOAN_PAY_002, LOAN_NONPAY_003):
        matched = df.filter(df["exposure_reference"] == loan_ref).to_dicts()
        assert len(matched) == 1, (
            f"P2.17: expected exactly 1 SA row for {loan_ref!r}, got {len(matched)}. "
            f"Pipeline may have dropped or duplicated the exposure."
        )
        rows[loan_ref] = matched[0]

    return rows


# ---------------------------------------------------------------------------
# P2.17 acceptance test
# ---------------------------------------------------------------------------


def test_crr_retail_payroll_loan_35pct_overrides_75pct_default(
    p2_17_crr_results: dict[str, dict],
) -> None:
    """
    CRR Art. 123 second subparagraph: payroll loans get 35%, not the flat 75%.

    Three retail loans are run through the CRR SA pipeline:
      - LOAN_PAY_001 (50k, is_payroll_loan=True):  expected RW=0.35, RWA=17,500
      - LOAN_PAY_002 (25k, is_payroll_loan=True):  expected RW=0.35, RWA=8,750
      - LOAN_NONPAY_003 (30k, is_payroll_loan=False): expected RW=0.75, RWA=22,500

    Anti-regression guards for the two payroll loans explicitly assert that
    risk_weight != 0.75 — a revert that re-flattens payroll to 75% will fail
    loudly on those assertions.

    Pre-fix failure: engine applies 75% flat to all retail, so LOAN_PAY_001 and
    LOAN_PAY_002 receive risk_weight=0.75 instead of 0.35.

    Arrange: P2.17 CRR bundle, CalculationConfig.crr(), base_currency="GBP",
             permission_mode=STANDARDISED, reporting_date=2026-06-30.
    Act:     full CRR SA pipeline.
    Assert:  per-row risk_weight and rwa_final match hand-calculated values.
    """
    import pytest as _pytest

    # ------------------------------------------------------------------
    # LOAN_PAY_001 — payroll, EAD=50,000, expected RW=0.35, RWA=17,500
    # ------------------------------------------------------------------
    row_pay_001 = p2_17_crr_results[LOAN_PAY_001]

    # Anti-regression guard: must not be the flat retail default
    assert row_pay_001["risk_weight"] != 0.75, (
        f"P2.17 LOAN_PAY_001 anti-regression: risk_weight must not be 0.75 "
        f"(CRR Art. 123 second subparagraph — payroll loan → 35%, not 75% flat). "
        f"A future revert of the payroll branch would re-introduce this bug."
    )

    assert row_pay_001["risk_weight"] == _pytest.approx(EXPECTED_RW_PAYROLL, abs=_RW_TOL), (
        f"P2.17 LOAN_PAY_001: expected risk_weight={EXPECTED_RW_PAYROLL} "
        f"(CRR Art. 123 second subparagraph — payroll/pension loan 35% RW), "
        f"got {row_pay_001['risk_weight']}. "
        f"Pre-fix: engine applies 75% flat (ignores is_payroll_loan)."
    )

    assert row_pay_001["rwa_final"] == _pytest.approx(EXPECTED_RWA_PAY_001, abs=_RWA_TOL), (
        f"P2.17 LOAN_PAY_001: expected rwa_final={EXPECTED_RWA_PAY_001:,.2f} "
        f"(EAD 50,000 × 0.35 = 17,500), "
        f"got {row_pay_001['rwa_final']:,.2f}. "
        f"Pre-fix: 50,000 × 0.75 = 37,500."
    )

    # ------------------------------------------------------------------
    # LOAN_PAY_002 — payroll, EAD=25,000, expected RW=0.35, RWA=8,750
    # ------------------------------------------------------------------
    row_pay_002 = p2_17_crr_results[LOAN_PAY_002]

    # Anti-regression guard
    assert row_pay_002["risk_weight"] != 0.75, (
        f"P2.17 LOAN_PAY_002 anti-regression: risk_weight must not be 0.75 "
        f"(CRR Art. 123 second subparagraph — payroll loan → 35%, not 75% flat). "
        f"A future revert of the payroll branch would re-introduce this bug."
    )

    assert row_pay_002["risk_weight"] == _pytest.approx(EXPECTED_RW_PAYROLL, abs=_RW_TOL), (
        f"P2.17 LOAN_PAY_002: expected risk_weight={EXPECTED_RW_PAYROLL} "
        f"(CRR Art. 123 second subparagraph — payroll/pension loan 35% RW), "
        f"got {row_pay_002['risk_weight']}. "
        f"Pre-fix: engine applies 75% flat (ignores is_payroll_loan)."
    )

    assert row_pay_002["rwa_final"] == _pytest.approx(EXPECTED_RWA_PAY_002, abs=_RWA_TOL), (
        f"P2.17 LOAN_PAY_002: expected rwa_final={EXPECTED_RWA_PAY_002:,.2f} "
        f"(EAD 25,000 × 0.35 = 8,750), "
        f"got {row_pay_002['rwa_final']:,.2f}. "
        f"Pre-fix: 25,000 × 0.75 = 18,750."
    )

    # ------------------------------------------------------------------
    # LOAN_NONPAY_003 — standard retail, EAD=30,000, RW=0.75, RWA=22,500
    # (control row — must be unaffected by the payroll fix)
    # ------------------------------------------------------------------
    row_nonpay_003 = p2_17_crr_results[LOAN_NONPAY_003]

    assert row_nonpay_003["risk_weight"] == _pytest.approx(EXPECTED_RW_RETAIL, abs=_RW_TOL), (
        f"P2.17 LOAN_NONPAY_003 (control): expected risk_weight={EXPECTED_RW_RETAIL} "
        f"(CRR Art. 123 first paragraph — standard retail 75% RW), "
        f"got {row_nonpay_003['risk_weight']}. "
        f"The payroll fix must not alter non-payroll retail loans."
    )

    assert row_nonpay_003["rwa_final"] == _pytest.approx(EXPECTED_RWA_NONPAY_003, abs=_RWA_TOL), (
        f"P2.17 LOAN_NONPAY_003 (control): expected rwa_final={EXPECTED_RWA_NONPAY_003:,.2f} "
        f"(EAD 30,000 × 0.75 = 22,500), "
        f"got {row_nonpay_003['rwa_final']:,.2f}."
    )
