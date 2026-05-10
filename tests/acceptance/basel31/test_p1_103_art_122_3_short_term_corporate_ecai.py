"""
P1.103 — B31 Art. 122(3) Table 6A Short-Term Corporate ECAI Risk Weight.

Acceptance scenario: a GBP 1,000,000 corporate exposure (entity_type=corporate,
CQS 3, 73-day maturity) carries a dedicated short-term ECAI assessment — a
**rating-row** flag (``is_short_term=True`` with ``scope_type='facility'`` /
``scope_id=FACILITY_REF``) attaches the short-term assessment to the specific
facility. Under PRA PS1/26 Art. 122(3) Table 6A the SA risk weight for a CQS
3 short-term ECAI rated corporate is 100%, not the 75% returned by Table 6
for the same CQS band under the long-term ECAI path.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator
    → OutputAggregator

Key assertion:
    risk_weight == 1.00  (Table 6A CQS 3, Art. 122(3))
    ead_final  == 1_000_000
    rwa_final  == 1_000_000
    k          == 80_000  (RWA × 8%)

Contrastive (no short-term rating row, same exposure):
    risk_weight == 0.75  — engine routes via Table 6 instead

Hand calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD   = drawn_amount + interest = 1,000,000 + 0 = 1,000,000
    RW    = Table 6A, CQS 3 = 1.00  (PRA PS1/26 Art. 122(3))
    RWA   = EAD × RW = 1,000,000 × 1.00 = 1,000,000
    K     = RWA × 0.08 = 80,000

Maturity (producer-side gate):
    value_date = 2027-01-01, maturity_date = 2027-03-15 → 73 days
    original_maturity_years = 73/365 ≈ 0.20 ≤ 0.25 → Art. 122(3) qualifies

References:
    PRA PS1/26 Art. 122(2): Table 6 long-term corporate ECAI risk weights
    PRA PS1/26 Art. 122(3): Table 6A short-term corporate ECAI risk weights
    src/rwa_calc/data/tables/b31_risk_weights.py: B31_CORPORATE_RISK_WEIGHTS (Table 6)
    src/rwa_calc/data/schemas.py: RATINGS_SCHEMA fields ``is_short_term``,
        ``scope_type``, ``scope_id``
    tests/fixtures/p1_103/p1_103.py: fixture constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_103.p1_103 import (
    EXPECTED_RISK_WEIGHT,
    FACILITY_REF,
    LOAN_REF,
    TABLE6_FALLBACK_RISK_WEIGHT,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_103"

# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped to run the pipeline only once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_103_sa_result() -> dict:
    """
    Run the P1.103 fixture through the Basel 3.1 SA pipeline.

    Constructs the RawDataBundle from scenario-local parquets (counterparty,
    facility, loan, rating).  The ratings parquet carries one row with
    ``is_short_term=True`` and ``scope_type='facility'`` attaching the short-
    term ECAI assessment to the test facility.

    The test uses inline LazyFrames for facility_mappings and lending_mappings
    because those tables have no P1.103-specific rows — the pipeline only needs
    them present with the correct schema.

    Returns the single result row for LN_CORP_ST_ECAI_01 as a dict.
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    # Ratings parquet carries is_short_term=True + scope_type='facility' for
    # the short-term ECAI route; the facility parquet is unchanged.
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")

    # Link the loan to the facility so the facility-scoped short-term rating
    # override propagates onto the loan exposure.
    facility_mappings = pl.LazyFrame(
        [
            {
                "parent_facility_reference": FACILITY_REF,
                "child_reference": LOAN_REF,
                "child_type": "loan",
            }
        ],
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
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
# P1.103 acceptance tests
# ---------------------------------------------------------------------------


class TestP1103Art1223Table6AShortTermECAI:
    """
    P1.103: Corporate with dedicated short-term ECAI (CQS 3, ≤3m) → 100% RW.

    Art. 122(3) Table 6A assigns higher risk weights than the long-term ECAI
    applied to a short-term exposure (Table 6).  For CQS 3 the contrast is:
        Table 6A (is_short_term=True rating attached to facility):  1.00
        Table 6  (no short-term rating attached):                   0.75
    """

    def test_p1_103_art_122_3_risk_weight_is_100_pct(
        self,
        p1_103_sa_result: dict,
    ) -> None:
        """
        Art. 122(3) Table 6A CQS 3 → risk_weight = 1.00.

        Arrange: corporate, entity_type=corporate, CQS 3, 73-day maturity,
                 short-term ECAI rating row attached to FACILITY_REF,
                 EAD = £1,000,000.
        Act:     Basel 3.1 SA pipeline (CalculationConfig.basel_3_1()).
        Assert:  risk_weight == 1.00  (Table 6A CQS 3 = 100%).

        References:
            PRA PS1/26 Art. 122(3): short-term corporate ECAI Table 6A.
        """
        # Arrange
        row = p1_103_sa_result
        table6a_rw = EXPECTED_RISK_WEIGHT  # 1.00 from fixture contract

        # Assert
        assert row["risk_weight"] == pytest.approx(table6a_rw, abs=1e-4), (
            f"P1.103 Art. 122(3): expected risk_weight={table6a_rw:.2f} "
            f"(Table 6A CQS 3 = 100%), "
            f"got {row['risk_weight']:.4f} "
            f"(engine still applies Table 6 fallback = {TABLE6_FALLBACK_RISK_WEIGHT:.2f})"
        )

    def test_p1_103_ead_is_1m(
        self,
        p1_103_sa_result: dict,
    ) -> None:
        """
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000.

        No CCF applies (on-balance-sheet loan), no CRM.

        Arrange: loan with drawn_amount=1,000,000, interest=0.
        Act:     Basel 3.1 SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_103_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(1_000_000.0), (
            f"P1.103: expected ead_final=1,000,000, got {row['ead_final']:,.0f}"
        )

    def test_p1_103_rwa_is_1m(
        self,
        p1_103_sa_result: dict,
    ) -> None:
        """
        RWA = EAD × RW = 1,000,000 × 1.00 = 1,000,000.

        Failure mode before fix:
            RWA = 1,000,000 × 0.75 = 750,000 (Table 6 path).

        Arrange: EAD=1,000,000, expected RW=1.00 (Art. 122(3) Table 6A CQS 3).
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 1,000,000.
        """
        # Arrange
        row = p1_103_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(1_000_000.0, rel=1e-4), (
            f"P1.103: expected rwa_final=1,000,000 "
            f"(EAD × 100% Table 6A), got {row['rwa_final']:,.0f}. "
            f"Engine currently returns {row['rwa_final']:,.0f} "
            f"(= EAD × {TABLE6_FALLBACK_RISK_WEIGHT:.0%} Table 6 fallback)"
        )

    def test_p1_103_capital_requirement_is_80k(
        self,
        p1_103_sa_result: dict,
    ) -> None:
        """
        K = RWA × 8% = 1,000,000 × 0.08 = 80,000.

        Derived from rwa_final since SA results do not carry a separate K column.

        Arrange: rwa_final expected = 1,000,000 after Art. 122(3) fix.
        Act:     compute k = rwa_final × 0.08.
        Assert:  k == 80,000.
        """
        # Arrange
        row = p1_103_sa_result

        # Act
        k = row["rwa_final"] * 0.08

        # Assert
        assert k == pytest.approx(80_000.0, rel=1e-4), (
            f"P1.103: expected k=80,000 (RWA × 8%), got {k:,.0f}. "
            f"(rwa_final={row['rwa_final']:,.0f})"
        )

    def test_p1_103_approach_applied_is_standardised(
        self,
        p1_103_sa_result: dict,
    ) -> None:
        """
        Exposure routes to standardised approach under SA-only config.

        Regression guard: exposure_class must be corporate and approach
        standardised — confirms the classification path is correct.

        Arrange: entity_type=corporate, CalculationConfig.basel_3_1(SA-only).
        Act:     Basel 3.1 SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_103_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.103: expected approach_applied='standardised', got {row['approach_applied']!r}"
        )
