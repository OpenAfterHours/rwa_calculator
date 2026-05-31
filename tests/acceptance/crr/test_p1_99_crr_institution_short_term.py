"""
P1.99: CRR Art. 120(2) Table 4 short-term rated institution risk weights.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate Art. 120(2) Table 4 risk weights for rated institutions with residual
  maturity <= 3 months (<=0.25 years), across all six CQS bands.
- Confirm that the short-term institution branch fires when original_maturity_years
  is derived as (maturity_date - value_date) / 365 < 0.25.

Scenario: six counterparties (entity_type=institution, country_code=DE), each with a
EUR 1,000,000 loan maturing in 90 days (2027-01-01 to 2027-04-01), and an external
ECAI rating mapping to CQS 1-6 respectively.  No collateral, no guarantees.

Hand-calculation (CRR Art. 120(2) Table 4):
    EAD = 1,000,000 EUR (drawn_amount; EUR -> GBP FX not applied — fx_rates omitted)
    original_maturity_years = 90/365 ≈ 0.2466 <= 0.25 -> Art. 120(2) gate fires

    CQS 1 -> RW 0.20  -> RWA  200,000
    CQS 2 -> RW 0.20  -> RWA  200,000
    CQS 3 -> RW 0.20  -> RWA  200,000
    CQS 4 -> RW 0.50  -> RWA  500,000
    CQS 5 -> RW 0.50  -> RWA  500,000
    CQS 6 -> RW 1.50  -> RWA 1,500,000

Note — regression-only test:
    The scenario-architect notes that the engine fix shipped in v0.2.6.
    This test therefore PASSES on first run.  It is intentionally retained as a
    regression pin: any future refactor of the short-term institution branch that
    silently breaks Art. 120(2) Table 4 will be caught here.

References:
    - CRR Art. 120(2) Table 4: short-term rated institution risk weights
    - src/rwa_calc/data/tables/crr_risk_weights.py: INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR
    - src/rwa_calc/engine/sa/namespace.py: _apply_crr_risk_weight_overrides short-term branch
    - tests/fixtures/p1_99/p1_99.py: fixture builder and EXPECTED_RISK_WEIGHTS
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.sa_bundle import build_sa_loan_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_99"

# ---------------------------------------------------------------------------
# Expected values (single source of truth from the fixture builder)
# ---------------------------------------------------------------------------

from tests.fixtures.p1_99.p1_99 import EAD, EXPECTED_RISK_WEIGHTS, EXPECTED_RWA  # noqa: E402

_CQS_LOAN_REFS = {cqs: f"LN-P199-INST-CQS{cqs}" for cqs in range(1, 7)}


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_99_sa_results() -> dict[int, dict]:
    """
    Run all six P1.99 rows through the CRR SA pipeline; return a dict keyed by CQS.

    Module-scoped to run the pipeline once and reuse results across all six
    parametrized test methods.

    Arrange:
        - Counterparties: six institution rows (entity_type=institution, DE, CQS 1-6)
        - Loans: six rows, EUR 1,000,000, 90-day maturity (residual ≈ 0.2466y <= 0.25y)
        - Ratings: six external ECAI ratings linking each counterparty to its CQS
        - Facilities / facility_mappings: empty (loan-only scenario)
        - Lending_mappings: empty (no retail lending group)
        - fx_rates: omitted (EUR loans remain at face value in pipeline)

    The pipeline derives original_maturity_years from (maturity_date - value_date) / 365
    when the field is absent from the loan row, so the 90-day loans hit the Art. 120(2)
    short-term gate automatically.
    """
    # Arrange — assemble the shared loan-only bundle from scenario-local parquets
    bundle = build_sa_loan_bundle(_FIXTURES_DIR)

    config = CalculationConfig.crr(
        reporting_date=date(2027, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()

    # Index rows by CQS via the loan_reference suffix pattern
    rows_by_cqs: dict[int, dict] = {}
    for cqs in range(1, 7):
        loan_ref = _CQS_LOAN_REFS[cqs]
        matched = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
        assert len(matched) == 1, (
            f"P1.99: expected exactly 1 SA row for {loan_ref}, got {len(matched)}"
        )
        rows_by_cqs[cqs] = matched[0]

    return rows_by_cqs


# ---------------------------------------------------------------------------
# P1.99 acceptance tests
# ---------------------------------------------------------------------------


class TestP199CRRInstitutionShortTerm:
    """
    P1.99: CRR Art. 120(2) Table 4 — short-term rated institution risk weights.

    Six parametrized tests (one per CQS band) verify:
      - risk_weight matches Table 4
      - rwa_final = EAD * risk_weight
      - ead_final = 1,000,000
      - exposure_class = 'institution' (SA classifier output)

    Regression-only: the engine fix shipped in v0.2.6 so all six tests pass today.
    The suite is retained to pin this behaviour against future refactors.
    """

    @pytest.mark.parametrize("cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_99_risk_weight_matches_table4(
        self, p1_99_sa_results: dict[int, dict], cqs: int
    ) -> None:
        """
        CRR Art. 120(2) Table 4: rated institution with maturity <= 3 months.

        Arrange: institution counterparty, CQS {cqs}, 90-day EUR 1M loan.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == EXPECTED_RISK_WEIGHTS[cqs].
        """
        # Arrange
        row = p1_99_sa_results[cqs]
        expected_rw = EXPECTED_RISK_WEIGHTS[cqs]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"P1.99 CQS {cqs}: expected risk_weight={expected_rw} "
            f"(CRR Art. 120(2) Table 4), got {row['risk_weight']}"
        )

    @pytest.mark.parametrize("cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_99_ead_final_is_one_million(
        self, p1_99_sa_results: dict[int, dict], cqs: int
    ) -> None:
        """
        EAD = drawn_amount = 1,000,000 EUR (no CCF, no CRM, no FX haircut).

        Arrange: EUR 1M drawn, interest=0, no collateral.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_99_sa_results[cqs]

        # Assert
        assert row["ead_final"] == pytest.approx(EAD, rel=1e-6), (
            f"P1.99 CQS {cqs}: expected ead_final={EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

    @pytest.mark.parametrize("cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_99_rwa_final_matches_ead_times_rw(
        self, p1_99_sa_results: dict[int, dict], cqs: int
    ) -> None:
        """
        RWA = EAD x RW per CRR Art. 120(2) Table 4.

        Expected values:
            CQS 1-3 ->  200,000  (0.20 x 1,000,000)
            CQS 4-5 ->  500,000  (0.50 x 1,000,000)
            CQS 6   -> 1,500,000 (1.50 x 1,000,000)
        """
        # Arrange
        row = p1_99_sa_results[cqs]
        expected_rwa = EXPECTED_RWA[cqs]

        # Assert
        assert row["rwa_final"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"P1.99 CQS {cqs}: expected rwa_final={expected_rwa:,.0f}, "
            f"got {row['rwa_final']:,.2f} "
            f"(EAD={row['ead_final']:,.0f} x RW={row['risk_weight']:.2f})"
        )

    @pytest.mark.parametrize("cqs", [1, 2, 3, 4, 5, 6])
    def test_p1_99_exposure_class_is_institution(
        self, p1_99_sa_results: dict[int, dict], cqs: int
    ) -> None:
        """
        SA classifier routes entity_type=institution to exposure_class 'institution'.

        This verifies the classifier correctly identifies the exposure class so that
        the Art. 120 institution risk weight branch fires (not corporate fallback).
        """
        # Arrange
        row = p1_99_sa_results[cqs]

        # Assert
        assert row["exposure_class"].lower() == "institution", (
            f"P1.99 CQS {cqs}: expected exposure_class='institution', got {row['exposure_class']!r}"
        )
