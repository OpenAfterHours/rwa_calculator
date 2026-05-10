"""
P1.105 — B31 Art. 120(2B) Table 4A Short-Term Institution ECAI Risk Weight.

Acceptance scenario: a GBP 1,000,000 institution exposure (entity_type=bank,
CQS 3, 73-day maturity) carries a dedicated short-term ECAI assessment
(has_short_term_ecai=True).  Under PRA PS1/26 Art. 120(2B) Table 4A the SA risk
weight for a CQS 3 short-term ECAI rated institution is 100%, not the 20%
returned by Table 4 for the same CQS band under the long-term ECAI path.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator
    → OutputAggregator

Key assertion (currently failing — engine routes to Table 4 regardless of
has_short_term_ecai flag, returning 0.20 instead of 1.00):
    risk_weight == 1.00  (Table 4A CQS 3, Art. 120(2B))
    ead_final  == 1_000_000
    rwa_final  == 1_000_000
    k          == 80_000  (RWA × 8%)

Contrastive (Table 4, has_short_term_ecai=False, same exposure):
    risk_weight == 0.20  — current engine output before P1.105 fix

Hand calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD   = drawn_amount + interest = 1,000,000 + 0 = 1,000,000
    RW    = Table 4A, CQS 3 = 1.00  (PRA PS1/26 Art. 120(2B))
    RWA   = EAD × RW = 1,000,000 × 1.00 = 1,000,000
    K     = RWA × 0.08 = 80,000

Maturity gate:
    value_date = 2027-01-01, maturity_date = 2027-03-15 → 73 days
    original_maturity_years = 73/365 ≈ 0.20 ≤ 0.25 → short-term gate fires
    has_short_term_ecai = True → Table 4A branch taken (not yet implemented)

References:
    PRA PS1/26 Art. 120(2B): Table 4A short-term ECAI assessment risk weights
    PRA PS1/26 Art. 120(3): interaction rules between Table 4 and Table 4A
    src/rwa_calc/data/tables/b31_risk_weights.py: B31_ECRA_SHORT_TERM_RISK_WEIGHTS
    src/rwa_calc/data/schemas.py: FACILITY_SCHEMA field `has_short_term_ecai` (Wave 4)
    tests/fixtures/p1_105/p1_105.py: fixture constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_105.p1_105 import (
    EXPECTED_RISK_WEIGHT,
    LOAN_REF,
    TABLE4_FALLBACK_RISK_WEIGHT,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_105"

# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped to run the pipeline only once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_105_sa_result() -> dict:
    """
    Run the P1.105 fixture through the Basel 3.1 SA pipeline.

    Constructs the RawDataBundle from scenario-local parquets (counterparty,
    facility, loan, rating).  The facility parquet includes ``has_short_term_ecai=True``
    appended by the fixture builder.

    The test uses inline LazyFrames for facility_mappings and lending_mappings
    because those tables have no P1.105-specific rows — the pipeline only needs
    them present with the correct schema.

    Returns the single result row for LN_INST_ST_ECAI_01 as a dict.
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    # Facility parquet carries has_short_term_ecai=True (fixture builder)
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")

    # Empty auxiliary tables with correct schema
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    bundle = RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=ratings,
    )

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run full Basel 3.1 SA pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results must not be None for SA-only config"

    df = results.sa_results.collect()
    rows = df.filter(pl.col("exposure_reference") == LOAN_REF).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 row for {LOAN_REF!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.105 acceptance tests
# ---------------------------------------------------------------------------


class TestP1105Art1202BTable4AShortTermECAI:
    """
    P1.105: Institution with dedicated short-term ECAI (CQS 3, ≤3m) → 100% RW.

    Art. 120(2B) Table 4A assigns higher risk weights than the long-term ECAI
    applied to a short-term exposure (Table 4).  For CQS 3 the contrast is:
        Table 4A (has_short_term_ecai=True):  1.00  ← expected after fix
        Table 4  (has_short_term_ecai=False): 0.20  ← current engine output

    Pre-fix failure mode:
        Engine does not read has_short_term_ecai and routes to Table 4 for
        all rated short-term institution exposures, returning RW = 0.20.
    """

    def test_p1_105_art_120_2b_risk_weight_is_100_pct(
        self,
        p1_105_sa_result: dict,
    ) -> None:
        """
        Art. 120(2B) Table 4A CQS 3 → risk_weight = 1.00.

        Arrange: institution, entity_type=bank, CQS 3, 73-day maturity,
                 has_short_term_ecai=True, EAD = £1,000,000.
        Act:     Basel 3.1 SA pipeline (CalculationConfig.basel_3_1()).
        Assert:  risk_weight == 1.00  (Table 4A CQS 3 = 100%).

        Failure mode before fix:
            Engine returns risk_weight == 0.20 (Table 4 path, ignores flag).

        References:
            PRA PS1/26 Art. 120(2B): short-term ECAI Table 4A.
        """
        # Arrange
        row = p1_105_sa_result
        table4a_rw = EXPECTED_RISK_WEIGHT  # 1.00 from fixture contract

        # Assert
        assert row["risk_weight"] == pytest.approx(table4a_rw, abs=1e-4), (
            f"P1.105 Art. 120(2B): expected risk_weight={table4a_rw:.2f} "
            f"(Table 4A CQS 3 = 100%), "
            f"got {row['risk_weight']:.4f} "
            f"(engine still applies Table 4 fallback = {TABLE4_FALLBACK_RISK_WEIGHT:.2f})"
        )

    def test_p1_105_ead_is_1m(
        self,
        p1_105_sa_result: dict,
    ) -> None:
        """
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000.

        No CCF applies (on-balance-sheet loan), no CRM.

        Arrange: loan with drawn_amount=1,000,000, interest=0.
        Act:     Basel 3.1 SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_105_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(1_000_000.0), (
            f"P1.105: expected ead_final=1,000,000, got {row['ead_final']:,.0f}"
        )

    def test_p1_105_rwa_is_1m(
        self,
        p1_105_sa_result: dict,
    ) -> None:
        """
        RWA = EAD × RW = 1,000,000 × 1.00 = 1,000,000.

        Failure mode before fix:
            RWA = 1,000,000 × 0.20 = 200,000 (Table 4 path).

        Arrange: EAD=1,000,000, expected RW=1.00 (Art. 120(2B) Table 4A CQS 3).
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 1,000,000.
        """
        # Arrange
        row = p1_105_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(1_000_000.0, rel=1e-4), (
            f"P1.105: expected rwa_final=1,000,000 "
            f"(EAD × 100% Table 4A), got {row['rwa_final']:,.0f}. "
            f"Engine currently returns {row['rwa_final']:,.0f} "
            f"(= EAD × {TABLE4_FALLBACK_RISK_WEIGHT:.0%} Table 4 fallback)"
        )

    def test_p1_105_capital_requirement_is_80k(
        self,
        p1_105_sa_result: dict,
    ) -> None:
        """
        K = RWA × 8% = 1,000,000 × 0.08 = 80,000.

        Derived from rwa_final since SA results do not carry a separate K column.

        Arrange: rwa_final expected = 1,000,000 after Art. 120(2B) fix.
        Act:     compute k = rwa_final × 0.08.
        Assert:  k == 80,000.
        """
        # Arrange
        row = p1_105_sa_result

        # Act
        k = row["rwa_final"] * 0.08

        # Assert
        assert k == pytest.approx(80_000.0, rel=1e-4), (
            f"P1.105: expected k=80,000 (RWA × 8%), got {k:,.0f}. "
            f"(rwa_final={row['rwa_final']:,.0f})"
        )

    def test_p1_105_approach_applied_is_standardised(
        self,
        p1_105_sa_result: dict,
    ) -> None:
        """
        Exposure routes to standardised approach under SA-only config.

        Regression guard: exposure_class must be institution and approach
        standardised — confirms the classification path is correct.

        Arrange: entity_type=bank, CalculationConfig.basel_3_1(SA-only).
        Act:     Basel 3.1 SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_105_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.105: expected approach_applied='standardised', got {row['approach_applied']!r}"
        )
