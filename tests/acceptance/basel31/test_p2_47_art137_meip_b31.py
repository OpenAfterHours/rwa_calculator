"""
P2.47: Basel 3.1 Art. 137(1)-(2) Table 9 — ECA MEIP score direct sovereign risk weight.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate that a sovereign counterparty with no ECAI rating but an ECA MEIP score of 2
  receives a 20% risk weight under Art. 137(2) Table 9 when running under Basel 3.1 config,
  not the 100% unrated fallback from Art. 114.
- Confirm the Art. 137 ECA path fires in _apply_b31_risk_weight_overrides (engine/sa/namespace.py)
  — the same CRR path (P1.100) is already implemented; the B31 dispatch branch is the gap.

Scenario: one sovereign counterparty (entity_type=sovereign, country_code=KZ,
sovereign_cqs=None, eca_score=2), with a USD 5,000,000 loan. No ECAI rating, no collateral,
no guarantees — clean single-factor SA test. Identical data to P1.100; only the config
differs (CalculationConfig.basel_3_1(), reporting_date=2027-01-15 vs CRR 2026-01-15).

Hand-calculation (Basel 3.1, Art. 137(2) Table 9 — unchanged from CRR):
    EAD     = drawn_amount = 5,000,000 (USD; interest=0, no FX)
    MEIP 2  → RW = 20% = 0.20     [Art. 137(2) Table 9]
    RWA     = EAD × RW = 5,000,000 × 0.20 = 1,000,000

Pre-implementation failure:
    _apply_b31_risk_weight_overrides has no cp_eca_score branch, so the B31 sovereign
    with eca_score=2 and sovereign_cqs=None falls through to the Art. 114 unrated 100%
    default, returning RW = 1.00 and RWA = 5,000,000 instead of 0.20 / 1,000,000.

References:
    - Art. 137(1): nomination of ECA for MEIP score assessment
    - Art. 137(2) Table 9: MEIP score to risk weight mapping (identical CRR and Basel 3.1)
    - PRA PS1/26 Art. 114: sovereign SA risk weights (unchanged from CRR)
    - tests/fixtures/p2_47/p2_47.py: fixture builder with scenario constants
    - src/rwa_calc/engine/sa/namespace.py: _apply_b31_risk_weight_overrides (fix target)
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

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_47"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, matches p2_47.py)
# ---------------------------------------------------------------------------

_LOAN_REF = "LN_B31_MEIP_001"
_EAD = 5_000_000.0
_EXPECTED_RW = 0.20  # Art. 137(2) Table 9, MEIP score 2
_EXPECTED_RWA = 1_000_000.0  # 0.20 × 5,000,000
# Regression sentinel: what the unrated Art. 114 fallback would produce
_UNRATED_FALLBACK_RW = 1.00


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_47_b31_sa_result() -> dict:
    """
    Run the P2.47 fixture through the Basel 3.1 SA pipeline and return the
    single result row for LN_B31_MEIP_001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - Counterparty: sovereign, Kazakhstan (country_code=KZ), sovereign_cqs=None,
          eca_score=2 (OECD consensus / ECA MEIP score).
        - Loan: USD 5,000,000, value_date=2027-01-15, maturity_date=2032-01-15.
        - Rating: placeholder row, cqs=None, pd=None (no ECAI assessment).
        - No facilities, no facility_mappings, no lending_mappings, no fx_rates.

    The engine must route via Art. 137(2) Table 9 (MEIP 2 → 20%) in the Basel 3.1
    arm (_apply_b31_risk_weight_overrides) rather than the Art. 114 unrated fallback
    (100%), because sovereign_cqs is absent and eca_score=2 is present.

    Pre-implementation: _apply_b31_risk_weight_overrides has no cp_eca_score branch,
    so risk_weight = 1.00 (Art. 114 unrated fallback) and rwa_final = 5,000,000.
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

    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 15),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()

    rows = df.filter(pl.col("exposure_reference") == _LOAN_REF).to_dicts()
    assert len(rows) == 1, (
        f"P2.47: expected exactly 1 SA row for {_LOAN_REF}, got {len(rows)}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P2.47 acceptance tests
# ---------------------------------------------------------------------------


class TestP247B31Art137ECAMeipSovereign:
    """
    P2.47: Basel 3.1 Art. 137(1)-(2) Table 9 — ECA MEIP score 2 → 20% sovereign risk weight.

    Five tests verify:
      - exposure_class == 'central_govt_central_bank' (classifier output for sovereign)
      - approach_applied == 'standardised'
      - ead_final == 5,000,000
      - risk_weight == 0.20 (Art. 137(2) Table 9, MEIP 2) — not the 100% fallback
      - rwa_final == 1,000,000 (EAD × 0.20)

    Load-bearing failure: _apply_b31_risk_weight_overrides has no cp_eca_score branch.
    The B31 sovereign with eca_score=2 and sovereign_cqs=None falls through to the
    Art. 114 unrated 100% default. risk_weight == 0.20 and rwa_final == 1,000,000
    will both fail with AssertionError until the engine-implementer adds the branch.
    """

    def test_p2_47_b31_art137_meip_exposure_class(self, p2_47_b31_sa_result: dict) -> None:
        """
        SA classifier routes entity_type=sovereign to exposure_class 'central_govt_central_bank'.

        Arrange: sovereign counterparty, no rating, eca_score=2, Basel 3.1 config.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  exposure_class == 'central_govt_central_bank'.
        """
        # Arrange
        row = p2_47_b31_sa_result

        # Assert
        assert row["exposure_class"].lower() == "central_govt_central_bank", (
            f"P2.47: expected exposure_class='central_govt_central_bank', "
            f"got {row['exposure_class']!r}"
        )

    def test_p2_47_b31_art137_meip_approach_applied(self, p2_47_b31_sa_result: dict) -> None:
        """
        SA-only config routes sovereign to 'standardised' approach.

        Arrange: PermissionMode.STANDARDISED, no IRB model on the rating row.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = p2_47_b31_sa_result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P2.47: expected approach_applied='standardised', got {row['approach_applied']!r}"
        )

    def test_p2_47_b31_art137_meip_ead_final(self, p2_47_b31_sa_result: dict) -> None:
        """
        EAD = drawn_amount = 5,000,000 (no CCF, no CRM, interest=0, no FX haircut).

        Arrange: USD 5M drawn, interest=0, no collateral.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  ead_final == 5,000,000.
        """
        # Arrange
        row = p2_47_b31_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(_EAD, rel=1e-6), (
            f"P2.47: expected ead_final={_EAD:,.0f}, got {row['ead_final']:,.2f}"
        )

    def test_p2_47_b31_art137_meip_risk_weight(self, p2_47_b31_sa_result: dict) -> None:
        """
        Art. 137(2) Table 9: sovereign with MEIP score 2 → RW = 20% under Basel 3.1.

        The fixture has sovereign_cqs=None (Kazakhstan, unrated) and eca_score=2.
        Without the B31 Art. 137 dispatch in _apply_b31_risk_weight_overrides the
        engine falls through to Art. 114 unrated fallback (RW = 1.00 = 100%).

        Arrange: sovereign counterparty, sovereign_cqs=None, eca_score=2, USD 5M loan,
                 CalculationConfig.basel_3_1().
        Act:     full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.20 (Art. 137(2) Table 9, MEIP 2).
        """
        # Arrange
        row = p2_47_b31_sa_result

        # Assert — expected Art. 137(2) risk weight
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW, abs=1e-6), (
            f"P2.47: expected risk_weight={_EXPECTED_RW} (Art. 137(2) Table 9, MEIP 2), "
            f"got {row['risk_weight']} — "
            f"if {_UNRATED_FALLBACK_RW} the Art. 137 ECA path is not firing in "
            f"_apply_b31_risk_weight_overrides (Art. 114 unrated fallback applied instead)"
        )

        # Anti-confound sentinel: ensure we are NOT on the unrated Art. 114 fallback path
        assert row["risk_weight"] != pytest.approx(_UNRATED_FALLBACK_RW, abs=1e-6), (
            f"P2.47: risk_weight={row['risk_weight']} matches the Art. 114 unrated fallback "
            f"(1.00) — Art. 137(2) ECA MEIP path must take precedence in "
            f"_apply_b31_risk_weight_overrides when sovereign_cqs is absent and "
            f"eca_score is present (Basel 3.1 arm)"
        )

    def test_p2_47_b31_art137_meip_rwa_final(self, p2_47_b31_sa_result: dict) -> None:
        """
        RWA = EAD × RW = 5,000,000 × 0.20 = 1,000,000 (Art. 137(2) Table 9, Basel 3.1).

        If the B31 Art. 137 ECA path is absent the engine produces 5,000,000 instead,
        a factor-of-5 capital overstatement.

        Arrange: EAD=5,000,000, RW=0.20 (MEIP 2).
        Act:     full Basel 3.1 SA pipeline.
        Assert:  rwa_final == 1,000,000.
        """
        # Arrange
        row = p2_47_b31_sa_result

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA, rel=1e-4), (
            f"P2.47: expected rwa_final={_EXPECTED_RWA:,.0f} (EAD × 0.20 per Art. 137(2)), "
            f"got {row['rwa_final']:,.2f} "
            f"(EAD={row['ead_final']:,.0f} x RW={row['risk_weight']:.2f})"
        )
