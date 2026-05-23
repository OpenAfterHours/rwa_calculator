"""
P1.128 — B31 Art. 121(4) SCRA short-term trade finance exception.

Acceptance scenario: a GBP 1,000,000 institution exposure (entity_type=bank,
SCRA Grade A, GB, unrated — no external CQS) with a 151-day original maturity
(2027-01-01 → 2027-06-01) and is_short_term_trade_lc=True.

Under PRA PS1/26 Art. 121(4) the short-term SCRA treatment is extended to
self-liquidating trade finance exposures with original maturity > 3 months
(0.25y) but ≤ 6 months (0.5y).  The 151-day maturity sits at 0.4137y, inside
this extended window.  Correctly applied, the SCRA Grade A short-term risk
weight of 20% must be used (B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"]).

Engine bug (pre-fix):
    engine/sa/namespace.py line ~558 gates the SCRA short-term branch on
    ``original_mty <= 0.25`` only.  The ``is_short_term_trade_lc`` OR-clause
    (equivalent to lines 525–527 in the ECRA branch) is missing.
    As a result the 151-day SCRA Grade A exposure falls through to the
    long-term branch → RW = 0.40, RWA = 400,000.

Key assertions (pre-fix failures):
    risk_weight == 0.20  (SCRA Grade A short-term, Art. 121(4))
    ead_final  == 1,000,000
    rwa_final  == 200,000
    k          == 16,000  (RWA × 8%)

Contrastive (long-term SCRA Grade A, engine before fix):
    risk_weight == 0.40  ← must NOT match

Hand calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD     = drawn_amount + interest = 1,000,000 + 0 = 1,000,000
    maturity = 151 days / 365 = 0.4137y
    Art. 121(4) gate: 0.25y < 0.4137y ≤ 0.5y AND is_short_term_trade_lc=True
    RW      = B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"] = 0.20  (Art. 121(4))
    RWA     = EAD × RW = 1,000,000 × 0.20 = 200,000
    K       = RWA × 0.08 = 16,000

References:
    PRA PS1/26 Art. 121(4): SCRA short-term treatment extended for trade finance.
    PRA PS1/26 Art. 121(3) / CRE20.18: SCRA Grade A short-term RW = 20%.
    src/rwa_calc/data/tables/b31_risk_weights.py: B31_SCRA_SHORT_TERM_RISK_WEIGHTS.
    src/rwa_calc/engine/sa/namespace.py: _b31_append_institution_maturity_branches.
    tests/fixtures/p1_128/p1_128.py: fixture constants.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_128.p1_128 import (
    EXPECTED_EAD,
    EXPECTED_K,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    LOAN_REF,
    SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT,
    SCRA_LONG_TERM_FALLBACK_RWA,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_128"

# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped to run the pipeline only once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_128_sa_result() -> dict:
    """
    Run the P1.128 fixture through the Basel 3.1 SA pipeline.

    Constructs the RawDataBundle from scenario-local parquets (counterparty,
    facility, loan, rating).  The facility parquet has is_short_term_trade_lc=True;
    no short-term ECAI rating row is attached and the ratings parquet is empty,
    forcing the SCRA (unrated) institution path.

    The test uses inline LazyFrames for facility_mappings and lending_mappings
    because those tables have no P1.128-specific rows — the pipeline only needs
    them present with the correct schema.

    Returns the single result row for LN_INST_SCRA_TRADE_01 as a dict.
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
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
# P1.128 acceptance tests
# ---------------------------------------------------------------------------


class TestP1128Art1214SCRAShortTermTradeFinance:
    """
    P1.128: Unrated institution (SCRA Grade A), 151-day trade-finance LC → 20% RW.

    Art. 121(4) extends the SCRA short-term window beyond 3 months (0.25y) to
    6 months (0.5y) for self-liquidating trade finance exposures.  For Grade A
    the contrast is:
        Art. 121(4) extended window (is_short_term_trade_lc=True):  0.20  ← expected
        Long-term SCRA Grade A (engine before fix):                 0.40  ← current

    Pre-fix failure mode:
        Engine SCRA short-term branch hard-codes ``original_mty <= 0.25``;
        the ``is_short_term_trade_lc`` OR-clause is absent, so the 151-day
        exposure (0.4137y) falls to the long-term branch → RW = 0.40.
    """

    def test_p1_128_art_121_4_risk_weight_is_20_pct(
        self,
        p1_128_sa_result: dict,
    ) -> None:
        """
        Art. 121(4) SCRA Grade A extended short-term → risk_weight = 0.20.

        Arrange: institution, entity_type=bank, SCRA Grade A, 151-day maturity,
                 is_short_term_trade_lc=True, no external rating, EAD = £1,000,000.
        Act:     Basel 3.1 SA pipeline (CalculationConfig.basel_3_1()).
        Assert:  risk_weight == 0.20  (B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"]).

        Failure mode before fix:
            Engine returns risk_weight == 0.40 (long-term SCRA Grade A path,
            is_short_term_trade_lc OR-clause missing from SCRA branch).

        References:
            PRA PS1/26 Art. 121(4): SCRA short-term extension for trade finance.
        """
        # Arrange
        row = p1_128_sa_result

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT, abs=1e-4), (
            f"P1.128 Art. 121(4): expected risk_weight={EXPECTED_RISK_WEIGHT:.2f} "
            f"(SCRA Grade A short-term = 20%), "
            f"got {row['risk_weight']:.4f} "
            f"(engine still applies long-term fallback = {SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT:.2f})"
        )

    def test_p1_128_ead_is_1m(
        self,
        p1_128_sa_result: dict,
    ) -> None:
        """
        EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000.

        No CCF applies (on-balance-sheet loan), no CRM.

        Arrange: loan with drawn_amount=1,000,000, interest=0.
        Act:     Basel 3.1 SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_128_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_EAD, rel=1e-4), (
            f"P1.128: expected ead_final={EXPECTED_EAD:,.0f}, got {row['ead_final']:,.0f}"
        )

    def test_p1_128_rwa_is_200k(
        self,
        p1_128_sa_result: dict,
    ) -> None:
        """
        RWA = EAD × RW = 1,000,000 × 0.20 = 200,000.

        Failure mode before fix:
            RWA = 1,000,000 × 0.40 = 400,000 (long-term SCRA path).

        Arrange: EAD=1,000,000, expected RW=0.20 (Art. 121(4) SCRA Grade A short-term).
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 200,000.
        """
        # Arrange
        row = p1_128_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA, rel=1e-4), (
            f"P1.128: expected rwa_final={EXPECTED_RWA:,.0f} "
            f"(EAD × 20% Art. 121(4) short-term), "
            f"got {row['rwa_final']:,.0f}. "
            f"Long-term fallback would give {SCRA_LONG_TERM_FALLBACK_RWA:,.0f} "
            f"(= EAD × {SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT:.0%})"
        )

    def test_p1_128_capital_requirement_is_16k(
        self,
        p1_128_sa_result: dict,
    ) -> None:
        """
        K = RWA × 8% = 200,000 × 0.08 = 16,000.

        Derived from rwa_final since SA results do not carry a separate K column.

        Arrange: rwa_final expected = 200,000 after Art. 121(4) fix.
        Act:     compute k = rwa_final × 0.08.
        Assert:  k == 16,000.
        """
        # Arrange
        row = p1_128_sa_result

        # Act
        k = row["rwa_final"] * 0.08

        # Assert
        assert k == pytest.approx(EXPECTED_K, rel=1e-4), (
            f"P1.128: expected k={EXPECTED_K:,.0f} (RWA × 8%), "
            f"got {k:,.0f}. "
            f"(rwa_final={row['rwa_final']:,.0f})"
        )

    def test_p1_128_approach_applied_is_standardised(
        self,
        p1_128_sa_result: dict,
    ) -> None:
        """
        Exposure routes to standardised approach under SA-only config.

        Regression guard: approach must be standardised — confirms the
        classification path and SA-only permission mode are respected.

        Arrange: entity_type=bank, CalculationConfig.basel_3_1(SA-only).
        Act:     Basel 3.1 SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p1_128_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.128: expected approach_applied='standardised', got {row['approach_applied']!r}"
        )
