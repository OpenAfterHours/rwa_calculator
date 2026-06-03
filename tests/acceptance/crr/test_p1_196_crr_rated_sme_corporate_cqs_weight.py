"""
P1.196 — CRR Art. 122 CQS-table risk weight for rated corporate-SME (CQS 1).

Acceptance scenario (CRR-SA-SME-CQS1): a rated corporate-SME with CQS 1 (AAA–AA-)
must use the Art. 122 Table 5 risk weight of 20%, NOT the unconditional 100%
corporate-SME override that the pre-fix engine applies.

Defect under test:
    ``sa/namespace.py:1383-1384`` applies the 100% corporate-SME override via
    ``uc.contains('CORPORATE') & uc.contains('SME')`` with no CQS gate.  A
    CQS 1 CORPORATE_SME is forced to 1.00, discarding the Art. 122 Table 5
    weight of 0.20 set by the ``rw_table`` join at ``namespace.py:1130``.
    This overstates RWA by 5x at the risk-weight step.

Hand calculation (EAD = GBP 1,000,000):
    exposure_class      = corporate_sme
    cqs                 = 1 (AA-)
    risk_weight         = 0.20  (Art. 122 Table 5 CQS 1 — NOT 1.00)
    rwa_pre_factor      = 1,000,000 × 0.20 = 200,000
    supporting_factor   = 0.7619  (Art. 501 tier-1, E* = 1,000,000 < GBP 2.2m)
    rwa_final           = 200,000 × 0.7619 = 152,380  (≈)

Pre-fix failure mode: risk_weight == 1.00 → rwa_pre_factor == 1,000,000
    → rwa_final == 761,900 (5x overstatement before Art. 501 SF is applied).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
    -> SACalculator -> OutputAggregator

References:
    CRR Art. 122 Table 5: corporate SA risk weights by CQS; CQS 1 = 20%.
    CRR Art. 501: SME supporting factor; tier-1 threshold GBP 2.2m; SF = 0.7619.
    src/rwa_calc/engine/sa/namespace.py:1383-1384 — defect site.
    src/rwa_calc/data/tables/crr_risk_weights.py:507-515 — CORPORATE_RISK_WEIGHTS.
    tests/fixtures/p1_196/p1_196.py — fixture module.
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

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_196"

# ---------------------------------------------------------------------------
# Expected values (single source of truth from the fixture builder)
# ---------------------------------------------------------------------------

from tests.fixtures.p1_196.p1_196 import (  # noqa: E402
    BUGGY_RW_BEFORE_FIX,
    EAD,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA_POST_FACTOR,
    EXPECTED_RWA_PRE_FACTOR,
    EXPECTED_SUPPORTING_FACTOR,
    LOAN_REF,
)

# Tolerances
_RW_TOL = 1e-6  # risk weight is a discrete lookup
_EAD_TOL = 1.0  # absolute GBP 1 — floating-point accumulation
_FACTOR_TOL = 1e-4  # supporting factor tolerance
_RWA_TOL = 1.0  # absolute GBP 1 for final RWA


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_196_sa_result() -> dict:
    """
    Run the single P1.196 row through the CRR SA pipeline and return its result dict.

    Module-scoped to run the pipeline once for all tests in this module.

    Arrange:
        - 1 counterparty: CP-SME-CQS1, entity_type=corporate, GB,
          annual_revenue=GBP 10m → classifier derives corporate_sme.
        - 1 loan: EXP-SME-CQS1, GBP 1,000,000, 3-year maturity, non-defaulted,
          not BTL. Below GBP 2.2m Art. 501 tier-1 threshold → SF = 0.7619.
        - 1 external rating: CQS 1 (AA-, long-term, issue-specific).
        - Config: CRR SA, STANDARDISED permissions.

    Returns:
        The single SA result row as a dict.
    """
    # Arrange
    bundle = build_sa_loan_bundle(_FIXTURES_DIR)
    config = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P1.196: SA results must not be None for SA-only (PermissionMode.STANDARDISED) config"
    )
    df = results.sa_results.collect()

    rows = df.filter(pl.col("exposure_reference") == LOAN_REF).to_dicts()
    assert len(rows) == 1, (
        f"P1.196: expected exactly 1 SA result row for {LOAN_REF!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.196 acceptance tests
# ---------------------------------------------------------------------------


class TestP1196CRRRatedSMECorporateCQSWeight:
    """
    CRR-SA-SME-CQS1: rated corporate-SME uses Art. 122 Table 5 CQS weight, not 100%.

    Pre-fix failure mode: the unconditional 100% corporate-SME override at
    namespace.py:1383-1384 fires for all CORPORATE_SME exposures regardless of CQS,
    overwriting the 0.20 Table 5 weight with 1.00. All risk_weight assertions fail
    under the unmodified engine.
    """

    def test_crr_sa_sme_cqs1_exposure_class_is_corporate_sme(self, p1_196_sa_result: dict) -> None:
        """
        Pre-condition: entity_type=corporate + annual_revenue=GBP 10m → corporate_sme.

        If this fails, the remaining risk-weight assertions are meaningless —
        the exposure did not reach the corporate-SME CQS override branch.

        Arrange: CP-SME-CQS1, entity_type=corporate, annual_revenue=GBP 10m.
        Act:     CRR SA pipeline.
        Assert:  exposure_class == 'corporate_sme'.
        """
        # Arrange
        row = p1_196_sa_result

        # Assert
        assert row["exposure_class"] == "corporate_sme", (
            f"P1.196: expected exposure_class='corporate_sme', "
            f"got {row['exposure_class']!r}. "
            f"Check annual_revenue threshold in classifier — "
            f"fixture sets annual_revenue=GBP 10m (below ~GBP 43.66m threshold)."
        )

    def test_crr_sa_sme_cqs1_risk_weight_is_20pct(self, p1_196_sa_result: dict) -> None:
        """
        CRR Art. 122 Table 5 CQS 1: risk_weight = 0.20 — primary load-bearing assertion.

        The rated corporate-SME with CQS 1 (AA-) must use the Art. 122 Table 5
        risk weight of 20%, NOT the unconditional 100% corporate-SME override
        applied by the pre-fix engine at namespace.py:1383-1384.

        Arrange: EXP-SME-CQS1, CQS 1 (AA-), EAD GBP 1,000,000.
        Act:     CRR SA pipeline under CalculationConfig.crr().
        Assert:  risk_weight == 0.20  (Art. 122 Table 5 CQS 1 = 20%).

        Pre-fix failure mode: risk_weight == 1.00 (unconditional SME override).
        """
        # Arrange
        row = p1_196_sa_result

        # Assert — primary load-bearing assertion
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT, abs=_RW_TOL), (
            f"CRR-SA-SME-CQS1 (PRIMARY): EXP-SME-CQS1 Art. 122 Table 5 CQS 1 → "
            f"expected risk_weight={EXPECTED_RISK_WEIGHT:.2f} (20%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine applies {BUGGY_RW_BEFORE_FIX:.2f} unconditionally via "
            f"namespace.py:1383-1384 (no CQS gate on the corporate-SME override)."
        )

    def test_crr_sa_sme_cqs1_risk_weight_is_not_buggy_100pct(self, p1_196_sa_result: dict) -> None:
        """
        Anti-confound regression sentinel: risk_weight must NOT be 1.00 (buggy value).

        Arrange: EXP-SME-CQS1, CQS 1, pre-fix engine returns 1.00.
        Act:     CRR SA pipeline.
        Assert:  risk_weight != 1.00.
        """
        # Arrange
        row = p1_196_sa_result

        # Assert — anti-confound
        assert row["risk_weight"] != pytest.approx(BUGGY_RW_BEFORE_FIX, abs=_RW_TOL), (
            f"CRR-SA-SME-CQS1 (ANTI-CONFOUND): EXP-SME-CQS1 risk_weight must NOT be "
            f"{BUGGY_RW_BEFORE_FIX:.2f} (Art. 122 corporate-SME 100% applies only to "
            f"unrated SME once gated, not CQS 1 rated SME). "
            f"Got {row['risk_weight']:.4f}."
        )

    def test_crr_sa_sme_cqs1_ead_final_is_1m(self, p1_196_sa_result: dict) -> None:
        """
        EAD = drawn_amount = GBP 1,000,000 (no CCF, no CRM, no FX haircut).

        Arrange: EXP-SME-CQS1, drawn_amount=1,000,000, interest=0, no collateral.
        Act:     CRR SA pipeline.
        Assert:  ead_final == 1,000,000.
        """
        # Arrange
        row = p1_196_sa_result

        # Assert
        assert row["ead_final"] == pytest.approx(EAD, abs=_EAD_TOL), (
            f"P1.196: expected ead_final={EAD:,.0f} (fully drawn, no CRM), "
            f"got {row['ead_final']:,.2f}"
        )

    def test_crr_sa_sme_cqs1_rwa_pre_factor_is_200k(self, p1_196_sa_result: dict) -> None:
        """
        RWA before Art. 501 SF = EAD × risk_weight = 1,000,000 × 0.20 = 200,000.

        Arrange: EXP-SME-CQS1, EAD=1,000,000, expected risk_weight=0.20.
        Act:     CRR SA pipeline.
        Assert:  rwa_pre_factor == 200,000.

        Pre-fix failure mode: rwa_pre_factor == 1,000,000 (EAD × 1.00).
        """
        # Arrange
        row = p1_196_sa_result

        # Assert
        assert row["rwa_pre_factor"] == pytest.approx(EXPECTED_RWA_PRE_FACTOR, abs=_RWA_TOL), (
            f"P1.196: expected rwa_pre_factor={EXPECTED_RWA_PRE_FACTOR:,.0f} "
            f"(EAD 1,000,000 × RW 0.20, Art. 122 CQS 1), "
            f"got {row['rwa_pre_factor']:,.2f}. "
            f"Pre-fix: {EAD * BUGGY_RW_BEFORE_FIX:,.0f} (EAD × 1.00)."
        )

    def test_crr_sa_sme_cqs1_supporting_factor_is_tier1(self, p1_196_sa_result: dict) -> None:
        """
        Art. 501 tier-1 supporting factor = 0.7619 (E* = 1,000,000 < GBP 2.2m).

        Arrange: EXP-SME-CQS1, EAD=1,000,000 < GBP 2,200,000 tier-1 threshold.
        Act:     CRR SA pipeline with SME supporting-factor enabled.
        Assert:  supporting_factor == 0.7619  and  supporting_factor_applied == True.
        """
        # Arrange
        row = p1_196_sa_result

        # Assert
        assert row["supporting_factor"] == pytest.approx(
            EXPECTED_SUPPORTING_FACTOR, abs=_FACTOR_TOL
        ), (
            f"P1.196: expected supporting_factor={EXPECTED_SUPPORTING_FACTOR} "
            f"(Art. 501 tier-1, E*=1,000,000 < GBP 2.2m), "
            f"got {row['supporting_factor']}"
        )
        assert row["supporting_factor_applied"] is True, (
            f"P1.196: expected supporting_factor_applied=True (is_sme=True, "
            f"not defaulted, not BTL, EAD < EUR 50m threshold), "
            f"got {row['supporting_factor_applied']}"
        )

    def test_crr_sa_sme_cqs1_rwa_final_is_152380(self, p1_196_sa_result: dict) -> None:
        """
        Final RWA = rwa_pre_factor × supporting_factor = 200,000 × 0.7619 ≈ 152,380.

        Arrange: EXP-SME-CQS1, EAD=1,000,000, RW=0.20, SF=0.7619.
        Act:     CRR SA pipeline.
        Assert:  rwa_final ≈ 152,380 (200,000 × 0.7619).

        Pre-fix failure mode: rwa_final ≈ 761,900 (1,000,000 × 0.7619 — 5x overstatement).
        """
        # Arrange
        row = p1_196_sa_result
        _BUGGY_RWA_FINAL = EAD * BUGGY_RW_BEFORE_FIX * EXPECTED_SUPPORTING_FACTOR  # 761,900

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_POST_FACTOR, abs=_RWA_TOL), (
            f"P1.196: expected rwa_final={EXPECTED_RWA_POST_FACTOR:,.2f} "
            f"(EAD 1,000,000 × RW 0.20 × SF 0.7619), "
            f"got {row['rwa_final']:,.2f}. "
            f"Pre-fix: {_BUGGY_RWA_FINAL:,.0f} (EAD × 1.00 × SF 0.7619 — 5x RW overstatement)."
        )
