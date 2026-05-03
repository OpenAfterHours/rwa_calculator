"""
P1.112: Non-UK unrated PSE sovereign-derived risk weight (Basel 3.1).

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Key responsibilities:
- Validate that an unrated non-UK PSE backed by a CQS 1 sovereign receives 20% RW
  per CRR Art. 116(1) Table 2 (sovereign-derived lookup), not the buggy 100% fallback.
- Bug: engine/sa/namespace.py uses cp_country_code == 'GB' guard, ignoring sovereign CQS
  for non-UK PSEs.

References:
- CRR Art. 116(1) Table 2 — sovereign-derived PSE risk weights
- PRA PS1/26 Art. 116(1) Table 2 (identical values)
- PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED in data/tables/crr_risk_weights.py
- IMPLEMENTATION_PLAN.md line 45 (P1.112)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_112"


# ---------------------------------------------------------------------------
# Session-scoped pipeline runner
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_112_sa_result() -> dict:
    """
    Run the P1.112 fixture through the Basel 3.1 SA pipeline and return the
    single result row for LN_PSE_DE_001 as a dict.

    Session-scoped to avoid re-running the pipeline per test method.
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    facility_mappings = pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet")
    fx_rates = pl.scan_parquet(_FIXTURES_DIR / "fx_rate.parquet")
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
        fx_rates=fx_rates,
    )

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()
    rows = df.filter(pl.col("exposure_reference") == "LN_PSE_DE_001").to_dicts()
    assert len(rows) == 1, f"Expected exactly 1 row for LN_PSE_DE_001, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# P1.112 acceptance tests
# ---------------------------------------------------------------------------


class TestP1112NonUKPSESovereignDerivedRW:
    """
    P1.112: Unrated non-UK PSE with CQS 1 sovereign must receive 20% RW.

    Art. 116(1) Table 2 maps sovereign CQS → PSE RW:
        CQS 1 → 20%
    The bug returns 100% for non-GB PSEs, overstating RWA 5×.
    """

    def test_risk_weight_is_20_pct(self, p1_112_sa_result: dict) -> None:
        """
        P1.112: PSE backed by CQS 1 sovereign → RW = 20%.

        Art. 116(1) Table 2: sovereign CQS 1 maps to PSE RW 20%.
        Current bug: non-UK PSE falls through to 100% instead of looking up
        sovereign CQS from PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED.
        """
        # Arrange
        row = p1_112_sa_result

        # Assert
        assert row["risk_weight"] == pytest.approx(0.20, abs=1e-6), (
            f"P1.112: Expected risk_weight=0.20 (Art. 116(1) Table 2 CQS 1 → 20%), "
            f"got {row['risk_weight']}"
        )

    def test_ead_final_is_100m(self, p1_112_sa_result: dict) -> None:
        """
        P1.112: EAD = 100,000,000 (fully drawn, no CCF, no CRM, FX 1.0 EUR→GBP).
        """
        # Arrange
        row = p1_112_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(100_000_000.0, rel=1e-6), (
            f"P1.112: Expected ead_final=100_000_000.0, got {row['ead_final']}"
        )

    def test_rwa_final_is_20m(self, p1_112_sa_result: dict) -> None:
        """
        P1.112: RWA = EAD × RW = 100,000,000 × 0.20 = 20,000,000.

        Current bug yields 100,000,000 (5× overstatement).
        """
        # Arrange
        row = p1_112_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(20_000_000.0, rel=1e-6), (
            f"P1.112: Expected rwa_final=20_000_000.0, got {row['rwa_final']}"
        )

    def test_approach_applied_is_standardised(self, p1_112_sa_result: dict) -> None:
        """
        P1.112: PSE under SA-only config routes to 'standardised' approach.
        """
        # Arrange
        row = p1_112_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.112: Expected approach_applied='standardised', got {row['approach_applied']!r}"
        )
