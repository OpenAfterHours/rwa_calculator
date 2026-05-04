"""
P1.121: CRR Art. 121(3) unrated institution short-term 20% risk weight.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate that an unrated institution with residual maturity <= 3 months (≤ 0.25y)
  receives 20% RW under CRR Art. 121(3), overriding the 100% sovereign-derived RW
  that would apply under Art. 121(1) Table 5 for sovereign_cqs=4 (Vietnam).
- Confirm the Art. 121(3) short-term gate fires when original_maturity_years is
  derived as (maturity_date - value_date) / 365 ≤ 0.25.

Scenario: one counterparty (entity_type=institution, country_code=VN, sovereign_cqs=4,
no external rating), with a USD 1,000,000 loan maturing in 85 days from value_date
(2026-01-15 to 2026-04-10; 85/365 ≈ 0.2329y ≤ 0.25y). No collateral, no guarantees.

Hand-calculation (CRR Art. 121, CalculationConfig.crr(reporting_date=date(2026,1,15))):
    EAD = drawn_amount = 1,000,000 (USD; interest=0)
    residual_maturity = 85 / 365 ≈ 0.2329y ≤ 0.25y → Art. 121(3) gate fires

    Without short-term override (Art. 121(1) Table 5, sovereign_cqs=4):
        RW = 1.00  →  RWA = 1,000,000

    With Art. 121(3) short-term override (correct):
        RW = 0.20  →  RWA =   200,000

Note — regression-only test:
    The scenario-architect notes this fix is already wired in the engine at
    engine/sa/namespace.py:547-548. This test PASSES on first run and is retained
    as a regression pin: any future refactor that silently breaks Art. 121(3) will
    produce risk_weight=1.00 instead of 0.20 (a 5× overstatement), caught here.

References:
    - CRR Art. 121(3): short-term unrated institution 20% RW (residual maturity ≤ 3m)
    - CRR Art. 121(1) Table 5: sovereign-derived unrated institution RW
    - src/rwa_calc/data/tables/crr_risk_weights.py: INSTITUTION_SHORT_TERM_UNRATED_RW_CRR
    - src/rwa_calc/engine/sa/namespace.py: unrated institution short-term branch
    - tests/fixtures/p1_121/p1_121.py: fixture builder
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_121"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, matches p1_121.py)
# ---------------------------------------------------------------------------

_LOAN_REF = "LN_CRR_A14_001"
_EAD = 1_000_000.0
_EXPECTED_RW = 0.20  # Art. 121(3) short-term unrated institution
_EXPECTED_RWA = 200_000.0  # 0.20 × 1,000,000
_LONG_TERM_RW = 1.00  # Art. 121(1) Table 5, sovereign_cqs=4 — what breaks if gate missing


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_121_sa_result() -> dict:
    """
    Run the P1.121 fixture through the CRR SA pipeline and return the single
    result row for LN_CRR_A14_001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - Counterparty: unrated institution, Vietnam (country_code=VN), sovereign_cqs=4
        - Loan: USD 1,000,000, value_date=2026-01-15, maturity_date=2026-04-10 (85 days)
        - Rating: internal placeholder, cqs=None (forces unrated SA path)
        - No facilities, no facility_mappings, no lending_mappings, no fx_rates.

    The pipeline derives original_maturity_years = (maturity_date - value_date) / 365
    when absent from the loan row; 85 / 365 ≈ 0.2329y ≤ 0.25y triggers Art. 121(3).
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")

    lending_mappings: pl.LazyFrame = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    bundle = RawDataBundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=lending_mappings,
        ratings=ratings,
    )

    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()

    rows = df.filter(pl.col("exposure_reference") == _LOAN_REF).to_dicts()
    assert len(rows) == 1, f"P1.121: expected exactly 1 SA row for {_LOAN_REF}, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# P1.121 acceptance tests
# ---------------------------------------------------------------------------


class TestP1121CRRArt1213UnratedInstShortTerm:
    """
    P1.121: CRR Art. 121(3) — short-term unrated institution 20% risk weight.

    Four tests verify:
      - exposure_class == 'institution' (classifier output)
      - approach_applied == 'standardised'
      - ead_final == 1,000,000
      - risk_weight == 0.20 (Art. 121(3) short-term gate, not Art. 121(1) 100%)
      - rwa_final == 200,000

    Regression-only: engine fix is already wired at namespace.py:547-548.
    All tests pass today; retained to pin this behaviour against future refactors.
    """

    def test_p1_121_art_121_3_unrated_inst_short_term_exposure_class(
        self, p1_121_sa_result: dict
    ) -> None:
        """
        SA classifier routes entity_type=institution to exposure_class 'institution'.

        Arrange: unrated Vietnamese institution, USD 1M 85-day loan.
        Act:     full CRR SA pipeline.
        Assert:  exposure_class == 'institution'.
        """
        # Arrange
        row = p1_121_sa_result

        # Assert
        assert row["exposure_class"].lower() == "institution", (
            f"P1.121: expected exposure_class='institution', got {row['exposure_class']!r}"
        )

    def test_p1_121_art_121_3_unrated_inst_short_term_approach(
        self, p1_121_sa_result: dict
    ) -> None:
        """
        SA-only config routes institution exposure to 'standardised' approach.

        Arrange: PermissionMode.STANDARDISED with no IRB model on the rating row.
        Act:     full CRR SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_121_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.121: expected approach_applied='standardised', got {row['approach_applied']!r}"
        )

    def test_p1_121_art_121_3_unrated_inst_short_term_ead(self, p1_121_sa_result: dict) -> None:
        """
        EAD = drawn_amount = 1,000,000 (no CCF, no CRM, interest=0).

        Arrange: USD 1M drawn, interest=0, no collateral.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_121_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(_EAD, rel=1e-6), (
            f"P1.121: expected ead_final={_EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

    def test_p1_121_art_121_3_unrated_inst_short_term_risk_weight(
        self, p1_121_sa_result: dict
    ) -> None:
        """
        CRR Art. 121(3): unrated institution with residual maturity ≤ 3 months → RW = 20%.

        The fixture has sovereign_cqs=4 (Vietnam), which gives RW = 100% under
        Art. 121(1) Table 5 long-term. Art. 121(3) overrides this to 20% when
        residual maturity is ≤ 0.25y (85 days / 365 ≈ 0.2329y here).

        Arrange: unrated institution, sovereign_cqs=4, 85-day loan (≤ 0.25y).
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.20 (not the long-term 1.00).
        """
        # Arrange
        row = p1_121_sa_result

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW, abs=1e-6), (
            f"P1.121: expected risk_weight={_EXPECTED_RW} (CRR Art. 121(3) short-term gate), "
            f"got {row['risk_weight']} — "
            f"if 1.00 the Art. 121(3) gate is not firing (Art. 121(1) Table 5 fallback)"
        )

    def test_p1_121_art_121_3_unrated_inst_short_term_rwa(self, p1_121_sa_result: dict) -> None:
        """
        RWA = EAD × RW = 1,000,000 × 0.20 = 200,000 (Art. 121(3)).

        Arrange: EAD=1,000,000, RW=0.20.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 200,000 (not 1,000,000 which would indicate 100% RW).
        """
        # Arrange
        row = p1_121_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA, rel=1e-4), (
            f"P1.121: expected rwa_final={_EXPECTED_RWA:,.0f}, "
            f"got {row['rwa_final']:,.2f} "
            f"(EAD={row['ead_final']:,.0f} x RW={row['risk_weight']:.2f})"
        )
