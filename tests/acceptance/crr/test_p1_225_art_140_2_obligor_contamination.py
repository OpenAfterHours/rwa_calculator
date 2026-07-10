"""
P1.225: CRR Art. 140(2)(a)/(b) — obligor-level short-term ECAI contamination.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate CRR Art. 140(2): when ANY of an obligor's short-term-ECAI-rated
  exposures maps (via Art. 131 Table 7) to 150% (CQS 4/5/6) or 50% (CQS 2),
  the obligor-level spillover applies to every UNRATED, UNSECURED claim on
  that obligor:
    Limb (a) — 150% at the trigger forces EVERY unrated unsecured claim
      (short- OR long-term) on the obligor to 150%.
    Limb (b) — 50% at the trigger floors unrated SHORT-TERM unsecured
      claims on the obligor at max(natural RW, 100%).
- Two obligors isolate the two limbs:
    CP-C1 (corporate): LN-F1 is ST-rated CQS 4 (Table 7 = 150%) -> limb (a)
      forces LN-L1 (long-term, unrated) and LN-L2 (short-term, unrated)
      from their natural Art. 122 UNRATED 100% up to 150%.
    CP-I1 (institution): LN-F2 is ST-rated CQS 2 (Table 7 = 50%) -> limb (b)
      floors LN-L3 (short-term, unrated) from its natural Art. 121(3)
      unrated-institution short-term 20% up to 100%.

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2026, 6, 30))):

    Limb (a) -- CP-C1 (corporate, unrated):
        LN-F1 (ST CQS 4, rated): Table 7 CQS 4 = 1.50 (not contaminated --
              already rated). EAD 1,000,000. RWA = 1,500,000.
        LN-L1 (unrated, unsecured, LONG-term): natural Art. 122 UNRATED =
              1.00; Art. 140(2)(a) forces RW = 1.50 (reaches the long-term
              leg -- the defect this scenario targets). EAD 2,000,000.
              RWA (post-fix) = 3,000,000 (baseline pre-fix RWA = 2,000,000).
        LN-L2 (unrated, unsecured, short-term): natural Art. 122 UNRATED =
              1.00; forced to 1.50 by the same Art. 140(2)(a) obligor flag.
              EAD 500,000. RWA (post-fix) = 750,000 (baseline 500,000).

    Limb (b) -- CP-I1 (institution, unrated):
        LN-F2 (ST CQS 2, rated): Table 7 CQS 2 = 0.50 (not floored --
              already rated). EAD 800,000. RWA = 400,000.
        LN-L3 (unrated, unsecured, short-term): natural Art. 121(3)
              unrated-institution short-term = 0.20; Art. 140(2)(b) floors
              RW = max(0.20, 1.00) = 1.00. EAD 600,000. RWA (post-fix)
              = 600,000 (baseline pre-fix RWA = 120,000).

    Headline fail-first assertions (new behaviour, engine-implementer
    target): LN-L1.risk_weight == 1.50, LN-L2.risk_weight == 1.50,
    LN-L3.risk_weight == 1.00. LN-F1 (1.50) and LN-F2 (0.50) are regression
    anchors -- already correct via the existing per-exposure Art. 131
    Table 7 override (P1.216/P1.224), unaffected by this fix.

References:
    - CRR Art. 140(2)(a)/(b) (obligor-level short-term-ECAI spillover);
      Art. 131 Table 7 (short-term credit assessment risk weights);
      Art. 122 (corporate unrated 100%); Art. 121(3) (unrated institution
      short-term 20%); Art. 140(1) (short-term treatment limited to
      institutions and corporates).
    - PRA PS1/26 Art. 140(2) (identical substance); Art. 120(2B) Table 4A;
      Art. 122(3) Table 6A (parity noted, not asserted by this test).
    - BCBS CRE21.17-21.18.
    - tests/fixtures/p1_225/p1_225.py: scenario constants and parquet builders.
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5,
      WS1, P1.225 (two-lens verified).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.sa_bundle import build_sa_loan_bundle
from tests.fixtures.p1_225.p1_225 import (
    EXPECTED_RISK_WEIGHT_LN_F1,
    EXPECTED_RISK_WEIGHT_LN_F2,
    EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX,
    EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX,
    EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX,
    EXPECTED_RWA_LN_F1,
    EXPECTED_RWA_LN_F2,
    EXPECTED_RWA_LN_L1_POST_FIX,
    EXPECTED_RWA_LN_L2_POST_FIX,
    EXPECTED_RWA_LN_L3_POST_FIX,
    LOAN_REF_F1,
    LOAN_REF_F2,
    LOAN_REF_L1,
    LOAN_REF_L2,
    LOAN_REF_L3,
    REPORTING_DATE_GUIDANCE,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_225"

_ALL_LOAN_REFS = (LOAN_REF_F1, LOAN_REF_L1, LOAN_REF_L2, LOAN_REF_F2, LOAN_REF_L3)

# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_225_sa_results() -> dict[str, dict]:
    """
    Run the P1.225 fixtures through the CRR SA pipeline once.

    Builds the shared loan-only RawDataBundle (counterparty/loan/rating
    parquets, no facilities/facility_mappings/lending_mappings rows) and runs
    a ``CalculationConfig.crr`` SA-only pipeline. Returns a mapping of
    loan_reference -> result row dict for all five loans.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.
    """
    # Arrange
    bundle = build_sa_loan_bundle(_FIXTURES_DIR)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE_GUIDANCE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()
    out: dict[str, dict] = {}
    for loan_ref in _ALL_LOAN_REFS:
        rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
        assert len(rows) == 1, f"P1.225: expected exactly 1 SA row for {loan_ref}, got {len(rows)}"
        out[loan_ref] = rows[0]
    return out


# ---------------------------------------------------------------------------
# P1.225 acceptance tests — Limb (a): CP-C1, 150% contamination
# ---------------------------------------------------------------------------


class TestP1225Art140_2LimbAContamination150:
    """
    P1.225 Limb (a) — CRR Art. 140(2)(a): obligor ST facility at 150% (CQS
    4/5/6) forces every unrated, unsecured claim on that obligor (short- OR
    long-term) to 150%.

    Pre-fix failure: LN-L1/LN-L2 remain at their natural Art. 122 UNRATED
    100%, understating RWA.
    """

    def test_p1_225_ln_f1_trigger_risk_weight_unchanged(
        self, p1_225_sa_results: dict[str, dict]
    ) -> None:
        """
        LN-F1 (the ST-rated CQS 4 trigger itself) is unaffected by
        contamination -- it is already rated via the per-exposure Art. 131
        Table 7 override.

        Arrange: CP-C1, LN-F1, loan-scoped short-term rating CQS 4.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.50 (Table 7 CQS 4, regression anchor).
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_F1]

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT_LN_F1, abs=1e-4), (
            f"P1.225 Limb (a): expected LN-F1 risk_weight="
            f"{EXPECTED_RISK_WEIGHT_LN_F1:.2f} (Art. 131 Table 7, CQS 4, "
            f"regression anchor), got {row['risk_weight']:.4f}"
        )

    def test_p1_225_ln_f1_trigger_rwa_unchanged(self, p1_225_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 1,000,000 x 1.50 = 1,500,000 (Table 7, unaffected
        by the obligor contamination the exposure itself triggers).

        Arrange: EAD=1,000,000, expected RW=1.50 (Art. 131 Table 7, CQS 4).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 1,500,000.
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_F1]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_LN_F1, rel=1e-4), (
            f"P1.225 Limb (a): expected LN-F1 rwa_final={EXPECTED_RWA_LN_F1:,.0f} "
            f"(EAD x 150% Table 7, regression anchor), got {row['rwa_final']:,.2f}"
        )

    def test_p1_225_ln_l1_long_term_unrated_risk_weight_forced_150(
        self, p1_225_sa_results: dict[str, dict]
    ) -> None:
        """
        CRR Art. 140(2)(a): CP-C1's ST facility (LN-F1) maps to 150% -> every
        unrated, unsecured claim on CP-C1 is forced to 150%, INCLUDING
        LN-L1's long-term claim -- the key distinction from the Art.
        120(3)(c) / P1.223 spillover, which is short-term-window-scoped
        only.

        Arrange: CP-C1, LN-L1, unrated, unsecured, 5-year maturity
                 (long-term, outside the short-term window).
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.50 (not the natural Art. 122 UNRATED 1.00).
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L1]

        # Assert
        assert row["risk_weight"] == pytest.approx(
            EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX, abs=1e-4
        ), (
            f"P1.225 Limb (a): expected LN-L1 risk_weight="
            f"{EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX:.2f} (Art. 140(2)(a) "
            f"obligor-level 150% force, reaching the long-term leg), got "
            f"{row['risk_weight']:.4f} (engine still applies the natural "
            f"Art. 122 UNRATED base weight = 1.00)"
        )

    def test_p1_225_ln_l1_long_term_unrated_rwa(self, p1_225_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 2,000,000 x 1.50 = 3,000,000 (Art. 140(2)(a) force).

        Failure mode before fix: RWA = 2,000,000 x 1.00 = 2,000,000
        (natural Art. 122 UNRATED, no obligor spillover).

        Arrange: EAD=2,000,000, expected RW=1.50 (Art. 140(2)(a) force).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 3,000,000.
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L1]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_LN_L1_POST_FIX, rel=1e-4), (
            f"P1.225 Limb (a): expected LN-L1 rwa_final="
            f"{EXPECTED_RWA_LN_L1_POST_FIX:,.0f} (EAD x 150% Art. 140(2)(a) "
            f"force), got {row['rwa_final']:,.2f}"
        )

    def test_p1_225_ln_l2_short_term_unrated_risk_weight_forced_150(
        self, p1_225_sa_results: dict[str, dict]
    ) -> None:
        """
        CRR Art. 140(2)(a): the same obligor-level 150% force reaches
        LN-L2, an unrated, unsecured, SHORT-term claim on CP-C1.

        Arrange: CP-C1, LN-L2, unrated, unsecured, 90-day maturity
                 (short-term window).
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.50 (not the natural Art. 122 UNRATED 1.00).
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L2]

        # Assert
        assert row["risk_weight"] == pytest.approx(
            EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX, abs=1e-4
        ), (
            f"P1.225 Limb (a): expected LN-L2 risk_weight="
            f"{EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX:.2f} (Art. 140(2)(a) "
            f"obligor-level 150% force), got {row['risk_weight']:.4f} "
            f"(engine still applies the natural Art. 122 UNRATED base "
            f"weight = 1.00)"
        )

    def test_p1_225_ln_l2_short_term_unrated_rwa(self, p1_225_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 500,000 x 1.50 = 750,000 (Art. 140(2)(a) force).

        Failure mode before fix: RWA = 500,000 x 1.00 = 500,000 (natural
        Art. 122 UNRATED, no obligor spillover).

        Arrange: EAD=500,000, expected RW=1.50 (Art. 140(2)(a) force).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 750,000.
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L2]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_LN_L2_POST_FIX, rel=1e-4), (
            f"P1.225 Limb (a): expected LN-L2 rwa_final="
            f"{EXPECTED_RWA_LN_L2_POST_FIX:,.0f} (EAD x 150% Art. 140(2)(a) "
            f"force), got {row['rwa_final']:,.2f}"
        )


# ---------------------------------------------------------------------------
# P1.225 acceptance tests — Limb (b): CP-I1, 100% floor
# ---------------------------------------------------------------------------


class TestP1225Art140_2LimbBFloor100:
    """
    P1.225 Limb (b) — CRR Art. 140(2)(b): obligor ST facility at 50%
    (CQS 2) floors unrated SHORT-TERM unsecured claims on that obligor at
    max(natural RW, 100%).

    Pre-fix failure: LN-L3 remains at its natural Art. 121(3) unrated-
    institution short-term 20%, understating RWA.
    """

    def test_p1_225_ln_f2_trigger_risk_weight_unchanged(
        self, p1_225_sa_results: dict[str, dict]
    ) -> None:
        """
        LN-F2 (the ST-rated CQS 2 trigger itself) is unaffected by the floor
        -- it is already rated via the per-exposure Art. 131 Table 7
        override.

        Arrange: CP-I1, LN-F2, loan-scoped short-term rating CQS 2.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.50 (Table 7 CQS 2, regression anchor).
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_F2]

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT_LN_F2, abs=1e-4), (
            f"P1.225 Limb (b): expected LN-F2 risk_weight="
            f"{EXPECTED_RISK_WEIGHT_LN_F2:.2f} (Art. 131 Table 7, CQS 2, "
            f"regression anchor), got {row['risk_weight']:.4f}"
        )

    def test_p1_225_ln_f2_trigger_rwa_unchanged(self, p1_225_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 800,000 x 0.50 = 400,000 (Table 7, unaffected by
        the obligor floor the exposure itself triggers).

        Arrange: EAD=800,000, expected RW=0.50 (Art. 131 Table 7, CQS 2).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 400,000.
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_F2]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_LN_F2, rel=1e-4), (
            f"P1.225 Limb (b): expected LN-F2 rwa_final={EXPECTED_RWA_LN_F2:,.0f} "
            f"(EAD x 50% Table 7, regression anchor), got {row['rwa_final']:,.2f}"
        )

    def test_p1_225_ln_l3_short_term_unrated_risk_weight_floored_100(
        self, p1_225_sa_results: dict[str, dict]
    ) -> None:
        """
        CRR Art. 140(2)(b): CP-I1's ST facility (LN-F2) maps to 50% -> every
        unrated SHORT-TERM claim on CP-I1 is floored at max(natural RW,
        100%). LN-L3's natural Art. 121(3) unrated-institution short-term
        weight (20%) is below the floor, so it is raised to 100%.

        Arrange: CP-I1, LN-L3, unrated, unsecured, 90-day maturity
                 (short-term window).
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.00 (not the natural Art. 121(3) 0.20).
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L3]

        # Assert
        assert row["risk_weight"] == pytest.approx(
            EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX, abs=1e-4
        ), (
            f"P1.225 Limb (b): expected LN-L3 risk_weight="
            f"{EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX:.2f} (Art. 140(2)(b) "
            f"obligor-level 100% floor), got {row['risk_weight']:.4f} "
            f"(engine still applies the natural Art. 121(3) unrated-"
            f"institution short-term base weight = 0.20)"
        )

    def test_p1_225_ln_l3_short_term_unrated_rwa(self, p1_225_sa_results: dict[str, dict]) -> None:
        """
        RWA = EAD x RW = 600,000 x 1.00 = 600,000 (Art. 140(2)(b) floor).

        Failure mode before fix: RWA = 600,000 x 0.20 = 120,000 (natural
        Art. 121(3) unrated-institution short-term, no obligor floor).

        Arrange: EAD=600,000, expected RW=1.00 (Art. 140(2)(b) floor).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 600,000.
        """
        # Arrange
        row = p1_225_sa_results[LOAN_REF_L3]

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_LN_L3_POST_FIX, rel=1e-4), (
            f"P1.225 Limb (b): expected LN-L3 rwa_final="
            f"{EXPECTED_RWA_LN_L3_POST_FIX:,.0f} (EAD x 100% Art. 140(2)(b) "
            f"floor), got {row['rwa_final']:,.2f}"
        )
