"""
B31-CCR-FLOOR-1: CCR-only portfolio — output floor S-TREA/U-TREA inclusion.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Scenario (P8.55 / B31-CCR-FLOOR-1):
    One counterparty (CP_CCR_1): institution, entity_type="institution", CQS 2, GB.
    No IRB model permission — U-TREA also routes through SA.
    One netting set (NS_CCR_1): unmargined, legally enforceable.
    One trade (T_CCR_1): 5y GBP IR derivative, notional=10m, MtM=10m, delta=1.

The bug under test (today's engine):
    SA-routed CCR rows are tagged approach_applied='standardised', which is
    excluded from FLOOR_ELIGIBLE_APPROACHES in engine/aggregator/_floor.py.
    As a result, OutputFloorSummary.s_trea=0.0 and u_trea=0.0 — even though
    the CCR-derived RWA (≈4,220,395) correctly reaches total_rwa_post_floor
    via the sa_rwa_total path.

Primary assertion (fails today, should pass post-fix):
    summary.s_trea == CCR_FLOOR1_GOLDEN_SA_RWA  (~4,220,395 -- today: 0.0)
    summary.u_trea == CCR_FLOOR1_GOLDEN_SA_RWA  (~4,220,395 -- today: 0.0)

Invariant assertion (holds both pre- and post-fix):
    summary.total_rwa_post_floor == CCR_FLOOR1_GOLDEN_SA_RWA
    This pins the engine fix to NOT double-count the CCR RWA.

References:
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - PS1/26 Art. 120(2) Table 3: institution CQS 2 -> 30% B31 ECRA RW
    - PS1/26 Art. 92(2A): output floor TREA = max(U-TREA, 0.725 * S-TREA + OF-ADJ)
    - tests/fixtures/ccr/golden_ccr_floor1.py: fixture builder and constants
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, OutputFloorSummary
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_floor1 import (
    CCR_FLOOR1_GOLDEN_SA_RWA,
    CCR_FLOOR1_GOLDEN_TOTAL_RWA_POST_FLOOR,
    CCR_FLOOR1_REPORTING_DATE,
    build_raw_data_bundle_ccr_floor1,
)

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_REL_TOL = 1e-6  # tight relative tolerance for non-round floats
_ABS_TOL = 1.0   # ±£1 absolute tolerance for portfolio-level floor values

# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_floor1_result() -> AggregatedResultBundle:
    """
    Run the B31-CCR-FLOOR-1 bundle through the Basel 3.1 SA pipeline.

    Arrange:
        - 1 trade (T_CCR_1): 5y GBP IR derivative, notional=10m, MtM=10m
        - 1 netting set (NS_CCR_1): CP_CCR_1, legally enforceable, unmargined
        - CP_CCR_1: institution, CQS 2, GB (entity_type="institution")
        - External rating: S&P "A" = CQS 2 (B31 ECRA, Table 3 -> 30% RW)
        - No CSA, no CCR collateral, no traditional lending, no IRB model
        - Reporting date: 2030-01-01 (Basel 3.1, 72.5% floor — fully phased-in)

    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_floor1()
    config = CalculationConfig.basel_3_1(
        reporting_date=CCR_FLOOR1_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run full Basel 3.1 pipeline
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# B31-CCR-FLOOR-1 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRFloor1OutputFloor:
    """
    B31-CCR-FLOOR-1: CCR SA RWA must appear in OutputFloorSummary S-TREA/U-TREA.

    Three assertions pin the bug and the invariant:
      1. s_trea == CCR_FLOOR1_GOLDEN_SA_RWA  (fails today: 0.0)
      2. u_trea == CCR_FLOOR1_GOLDEN_SA_RWA  (fails today: 0.0)
      3. floor_threshold == 0.725 * CCR_FLOOR1_GOLDEN_SA_RWA (fails today: 0.0)
      4. total_rwa_post_floor == CCR_FLOOR1_GOLDEN_SA_RWA  (passes today, invariant)
      5. portfolio_floor_binding is False  (floor non-binding once s_trea is correct)

    The first failing assertion (s_trea == approx(4_220_395.77)) is the
    load-bearing TDD signal for the engine-implementer.

    References:
        - PS1/26 Art. 92(2A): S-TREA must include CCR SA-equivalent RWA
        - tests/fixtures/ccr/golden_ccr_floor1.py: CCR_FLOOR1_GOLDEN_SA_RWA constant
    """

    def test_b31_ccr_floor1_output_floor_summary_exists(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        Basel 3.1 CCR pipeline populates OutputFloorSummary.

        Arrange: B31-CCR-FLOOR-1 bundle (SA-only CCR, reporting_date=2030-01-01).
        Act:     full Basel 3.1 pipeline.
        Assert:  output_floor_summary is not None and is OutputFloorSummary.

        This is a prerequisite for the primary assertions — the summary object
        must exist before S-TREA/U-TREA can be checked.
        """
        # Arrange + Act — via fixture
        summary = ccr_floor1_result.output_floor_summary

        # Assert
        assert summary is not None, (
            "B31-CCR-FLOOR-1: output_floor_summary must be populated for a Basel 3.1 run "
            "with reporting_date=2030-01-01 (fully-phased 72.5% output floor). "
            "Got None — check that the OutputAggregator creates a summary under Basel 3.1."
        )
        assert isinstance(summary, OutputFloorSummary), (
            f"B31-CCR-FLOOR-1: output_floor_summary must be an OutputFloorSummary instance, "
            f"got {type(summary)!r}."
        )

    def test_b31_ccr_floor1_s_trea_includes_ccr_rwa(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        S-TREA must include the CCR SA-equivalent RWA (≈4,220,395.77).

        PRIMARY FAILING ASSERTION (today: s_trea == 0.0, bug in _floor.py).

        Arrange: B31-CCR-FLOOR-1 bundle (SA-only CCR, CQS 2 institution, 30% RW).
        Act:     full Basel 3.1 pipeline.
        Assert:  s_trea == approx(CCR_FLOOR1_GOLDEN_SA_RWA, abs=1.0).

        The CCR synthetic row is tagged approach_applied='standardised'.  Today
        FLOOR_ELIGIBLE_APPROACHES excludes 'standardised', so s_trea = 0.0.
        The fix must include CCR-routed SA rows in the S-TREA numerator.

        References:
            - PS1/26 Art. 92(2A): S-TREA is the SA-equivalent RWA for ALL
              floor-eligible exposures, including CCR SA rows.
        """
        # Arrange + Act — via fixture
        summary = ccr_floor1_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert — PRIMARY FAILING ASSERTION
        assert summary.s_trea == pytest.approx(CCR_FLOOR1_GOLDEN_SA_RWA, abs=_ABS_TOL), (
            f"B31-CCR-FLOOR-1: s_trea must equal CCR SA RWA "
            f"(expected ≈{CCR_FLOOR1_GOLDEN_SA_RWA:,.2f}, got {summary.s_trea:,.2f}). "
            "Bug: SA-tagged CCR rows are excluded from FLOOR_ELIGIBLE_APPROACHES in "
            "engine/aggregator/_floor.py. The fix must include CCR-derived SA rows "
            "in the S-TREA computation (PS1/26 Art. 92(2A))."
        )

    def test_b31_ccr_floor1_u_trea_includes_ccr_rwa(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        U-TREA must equal S-TREA for a pure-SA CCR portfolio (no IRB model).

        Arrange: B31-CCR-FLOOR-1 (SA-only CCR — no IRB model permission).
        Act:     full Basel 3.1 pipeline.
        Assert:  u_trea == approx(CCR_FLOOR1_GOLDEN_SA_RWA, abs=1.0).

        When there is no IRB model permission, the U-TREA leg also routes through SA.
        Because S-TREA == U-TREA for a pure-SA CCR portfolio, u_trea must equal
        the same CCR-derived SA RWA. Today: 0.0 (same bug as s_trea).

        References:
            - PS1/26 Art. 92(2A): U-TREA = actual RWA for floor-eligible exposures
        """
        # Arrange + Act — via fixture
        summary = ccr_floor1_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.u_trea == pytest.approx(CCR_FLOOR1_GOLDEN_SA_RWA, abs=_ABS_TOL), (
            f"B31-CCR-FLOOR-1: u_trea must equal CCR SA RWA for a pure-SA CCR portfolio "
            f"(expected ≈{CCR_FLOOR1_GOLDEN_SA_RWA:,.2f}, got {summary.u_trea:,.2f}). "
            "When no IRB model permission exists, U-TREA == S-TREA for CCR exposures. "
            "Bug: u_trea = 0.0 because SA-tagged CCR rows are excluded from the "
            "floor computation (PS1/26 Art. 92(2A))."
        )

    def test_b31_ccr_floor1_floor_threshold(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        floor_threshold == 0.725 * s_trea (no OF-ADJ inputs, 2030 reporting date).

        Arrange: B31-CCR-FLOOR-1; OF-ADJ = 0 (no gcra_amount, no sa_t2_credit,
                 no art_40_deductions in config); reporting_date=2030-01-01
                 -> fully-phased 72.5% floor (PRA PS1/26 Art. 92(5)).
        Act:     full Basel 3.1 pipeline.
        Assert:  floor_threshold == approx(0.725 * CCR_FLOOR1_GOLDEN_SA_RWA, abs=1.0).

        Today: floor_threshold = 0.0 (derived from s_trea=0.0).

        References:
            - PS1/26 Art. 92(2A): floor_threshold = floor_pct * S-TREA + OF-ADJ
        """
        # Arrange
        expected_floor_threshold = 0.725 * CCR_FLOOR1_GOLDEN_SA_RWA

        # Act — via fixture
        summary = ccr_floor1_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.floor_threshold == pytest.approx(
            expected_floor_threshold, abs=_ABS_TOL
        ), (
            f"B31-CCR-FLOOR-1: floor_threshold must equal 0.725 * s_trea "
            f"(expected ≈{expected_floor_threshold:,.2f}, "
            f"got {summary.floor_threshold:,.2f}). "
            "floor_threshold = floor_pct * S-TREA + OF-ADJ; OF-ADJ=0 here. "
            "Today: floor_threshold=0.0 because s_trea=0.0 (same root bug). "
            "(PS1/26 Art. 92(2A))."
        )

    def test_b31_ccr_floor1_total_rwa_post_floor_invariant(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        INVARIANT: total_rwa_post_floor == CCR_FLOOR1_GOLDEN_SA_RWA (pre- and post-fix).

        This assertion holds TODAY (total_rwa_post_floor is correct via the
        sa_rwa_total path) and must ALSO hold after the engine fix — it ensures
        the implementer does not double-count the CCR RWA by adding it to both
        the floor numerator AND the sa_rwa_total path.

        Floor non-binding check:
            0.725 * s_trea (≈3,059,787) < u_trea (≈4,220,396) → floor does NOT bind.
            total_rwa_post_floor = u_trea (no shortfall add-on).

        Arrange: B31-CCR-FLOOR-1 (SA-only CCR, no IRB, reporting_date=2030-01-01).
        Act:     full Basel 3.1 pipeline.
        Assert:  total_rwa_post_floor == approx(CCR_FLOOR1_GOLDEN_TOTAL_RWA_POST_FLOOR).

        References:
            - PS1/26 Art. 92(2A): total_rwa_post_floor = floored_modelled + sa_total + equity_total
        """
        # Arrange + Act — via fixture
        summary = ccr_floor1_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert — INVARIANT (holds today and must hold post-fix)
        assert summary.total_rwa_post_floor == pytest.approx(
            CCR_FLOOR1_GOLDEN_TOTAL_RWA_POST_FLOOR, abs=_ABS_TOL
        ), (
            f"B31-CCR-FLOOR-1: total_rwa_post_floor must equal the CCR SA RWA "
            f"(expected ≈{CCR_FLOOR1_GOLDEN_TOTAL_RWA_POST_FLOOR:,.2f}, "
            f"got {summary.total_rwa_post_floor:,.2f}). "
            "This invariant must hold both before and after the engine fix — "
            "it prevents double-counting the CCR RWA in the portfolio total. "
            "Floor does not bind (0.725 * 4.22m < 4.22m), so total = sa_ccr_rwa. "
            "(PS1/26 Art. 92(2A))."
        )

    def test_b31_ccr_floor1_floor_not_binding(
        self, ccr_floor1_result: AggregatedResultBundle
    ) -> None:
        """
        portfolio_floor_binding is False (floor non-binding when s_trea is correct).

        0.725 * s_trea (≈3,059,787) < u_trea (≈4,220,396) → floor does NOT bind.
        This is expected post-fix. Pre-fix, when s_trea=u_trea=0.0, the flag is
        also False (floor non-binding against zero), but for the wrong reason.

        Arrange: B31-CCR-FLOOR-1 (pure-SA CCR, CQS 2, 30% RW).
        Act:     full Basel 3.1 pipeline.
        Assert:  portfolio_floor_binding is False.

        References:
            - PS1/26 Art. 92(2A): TREA = max(U-TREA, floor_threshold) — non-binding here
        """
        # Arrange + Act — via fixture
        summary = ccr_floor1_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.portfolio_floor_binding is False, (
            f"B31-CCR-FLOOR-1: portfolio_floor_binding must be False "
            f"(0.725 * s_trea < u_trea for a pure-SA CCR portfolio). "
            f"Got portfolio_floor_binding={summary.portfolio_floor_binding!r}, "
            f"u_trea={summary.u_trea:,.2f}, s_trea={summary.s_trea:,.2f}, "
            f"floor_threshold={summary.floor_threshold:,.2f}. "
            "(PS1/26 Art. 92(2A))."
        )
