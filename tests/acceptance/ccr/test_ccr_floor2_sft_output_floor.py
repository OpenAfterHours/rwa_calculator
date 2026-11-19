"""
B31-CCR-FLOOR-2: FCCM SFT portfolio — output floor S-TREA/U-TREA inclusion.

Pipeline position:
    Loader -> HierarchyResolver -> ccr_sa_ccr -> sft_fccm -> Classifier
    -> CRMProcessor -> SACalculator -> OutputAggregator

Scenario (SFT/FCCM separation Phase 7a — operator decision Q1):
    One FCCM SFT (T_SFT_001, GBP 60.7m corp bond CQS 1 residual 7y) in netting
    set NS_SFT_001 against CP_INST_001 (institution, CQS 2, GB). No IRB model
    permission — the U-TREA leg also routes through SA, so S-TREA == U-TREA.
    Reporting date 2030-01-01 (Basel 3.1, fully-phased 72.5% output floor).

The behaviour change under test:
    Before Phase 7a, the floor tag in engine/stages/calc.py keyed only on
    risk_type == "CCR_DERIVATIVE". FCCM SFTs kept the plain "standardised" tag
    and were EXCLUDED from the output-floor S-TREA / U-TREA numerators
    (s_trea == 0.0). After Phase 7a, the predicate also matches
    risk_type == "CCR_SFT", so the SFT row receives the floor-eligible
    "standardised_ccr" tag and ENTERS the floor numerator.

Primary assertions:
    1. The SFT synthetic row carries approach_applied == "standardised_ccr"
       (the floor tag fired — load-bearing signal for the predicate change).
    2. summary.s_trea == sft_rwa  (SFT RWA is in the floor numerator; pre-fix 0.0)
    3. summary.u_trea == sft_rwa  (pure-SA SFT portfolio: U-TREA == S-TREA)

Invariant:
    summary.total_rwa_post_floor == sft_rwa  (floor non-binding, no double-count)

References:
    - PS1/26 Art. 92(2A): output floor TREA = max(U-TREA, 0.725 × S-TREA + OF-ADJ)
    - PS1/26 Art. 92(3A): SFTs are NOT on the S-TREA exclusion list
    - CRR Art. 271(2), 223(5): FCCM SFT EAD
    - tests/fixtures/ccr/golden_ccr_floor2_sft.py: fixture builder and constants
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.aggregator._schemas import SA_CCR_APPROACH
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_floor2_sft import (
    CCR_FLOOR2_EXPOSURE_REFERENCE,
    CCR_FLOOR2_GOLDEN_SFT_RWA,
    CCR_FLOOR2_GOLDEN_TOTAL_RWA_POST_FLOOR,
    CCR_FLOOR2_REPORTING_DATE,
    build_raw_data_bundle_ccr_floor2_sft,
)

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_REL_TOL = 1e-6  # tight relative tolerance for non-round floats
_ABS_TOL = 1.0  # ±£1 absolute tolerance for portfolio-level floor values


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_floor2_result() -> AggregatedResultBundle:
    """
    Run the B31-CCR-FLOOR-2 FCCM SFT bundle through the Basel 3.1 SA pipeline.

    Arrange:
        - 1 SFT (T_SFT_001): GBP 60.7m corp bond CQS 1 residual 7y, NS_SFT_001,
          supplied via raw.sft (the peer sft_fccm stage).
        - CP_INST_001: institution, CQS 2, GB; no IRB model.
        - Reporting date 2030-01-01 (Basel 3.1, 72.5% floor — fully phased-in).

    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().
    """
    bundle = build_raw_data_bundle_ccr_floor2_sft()
    config = CalculationConfig.basel_3_1(
        reporting_date=CCR_FLOOR2_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _sft_row(result: AggregatedResultBundle) -> dict:
    """Return the single FCCM SFT synthetic row from the result frame."""
    results = result.results
    df = results.collect() if isinstance(results, pl.LazyFrame) else results
    sft = df.filter(pl.col("risk_type") == "CCR_SFT")
    assert sft.height == 1, f"B31-CCR-FLOOR-2: expected exactly one CCR_SFT row, got {sft.height}."
    return sft.to_dicts()[0]


# ---------------------------------------------------------------------------
# B31-CCR-FLOOR-2 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRFloor2SFTOutputFloor:
    """FCCM SFT RWA must appear in the output-floor S-TREA/U-TREA numerator."""

    def test_b31_ccr_floor2_sft_row_carries_floor_tag(
        self, ccr_floor2_result: AggregatedResultBundle
    ) -> None:
        """
        The FCCM SFT synthetic row carries approach_applied == "standardised_ccr".

        Arrange: B31-CCR-FLOOR-2 (one uncollateralised FCCM SFT, B3.1 2030-01-01).
        Act:     full Basel 3.1 pipeline.
        Assert:  the CCR_SFT row's approach_applied == SA_CCR_APPROACH.

        This is the load-bearing signal that the Phase 7a predicate change fired:
        before Phase 7a the SFT row kept approach_applied == "standardised" and
        was excluded from FLOOR_ELIGIBLE_APPROACHES.

        References:
            - PS1/26 Art. 92(3A): SFTs enter the S-TREA numerator.
        """
        # Arrange + Act — via fixture
        row = _sft_row(ccr_floor2_result)

        # Assert
        assert row["exposure_reference"] == CCR_FLOOR2_EXPOSURE_REFERENCE
        assert row["approach_applied"] == SA_CCR_APPROACH, (
            f"B31-CCR-FLOOR-2: FCCM SFT row must carry approach_applied="
            f"{SA_CCR_APPROACH!r} so it enters FLOOR_ELIGIBLE_APPROACHES "
            f"(PS1/26 Art. 92(3A)). Got {row['approach_applied']!r}. Before "
            "Phase 7a the floor tag keyed only on risk_type=='CCR_DERIVATIVE', "
            "leaving SFTs tagged 'standardised' and out of the floor numerator."
        )

    def test_b31_ccr_floor2_s_trea_includes_sft_rwa(
        self, ccr_floor2_result: AggregatedResultBundle
    ) -> None:
        """
        S-TREA must include the FCCM SFT SA-equivalent RWA.

        Arrange: B31-CCR-FLOOR-2 (pure-SA FCCM SFT, institution).
        Act:     full Basel 3.1 pipeline.
        Assert:  s_trea == sft_rwa == CCR_FLOOR2_GOLDEN_SFT_RWA.

        The assertion is self-deriving — s_trea must equal the SFT row's own
        rwa_final — AND pins the golden value. Pre-Phase-7a s_trea == 0.0.

        References:
            - PS1/26 Art. 92(3A): SFTs are NOT on the S-TREA exclusion list.
        """
        # Arrange + Act — via fixture
        summary = ccr_floor2_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"
        row = _sft_row(ccr_floor2_result)
        sft_rwa = float(row["rwa_final"])

        # Assert — self-deriving inclusion proof + golden pin
        assert summary.s_trea == pytest.approx(sft_rwa, rel=_REL_TOL), (
            f"B31-CCR-FLOOR-2: s_trea must equal the FCCM SFT row's rwa_final "
            f"(expected ≈{sft_rwa:,.2f}, got {summary.s_trea:,.2f}). The SFT RWA "
            "must enter the S-TREA numerator (PS1/26 Art. 92(3A)). Pre-Phase-7a "
            "s_trea == 0.0 because SFTs were tagged 'standardised'."
        )
        assert summary.s_trea == pytest.approx(CCR_FLOOR2_GOLDEN_SFT_RWA, abs=_ABS_TOL), (
            f"B31-CCR-FLOOR-2: golden S-TREA pin "
            f"(expected ≈{CCR_FLOOR2_GOLDEN_SFT_RWA:,.2f}, got {summary.s_trea:,.2f})."
        )

    def test_b31_ccr_floor2_u_trea_equals_s_trea(
        self, ccr_floor2_result: AggregatedResultBundle
    ) -> None:
        """
        U-TREA == S-TREA for a pure-SA FCCM SFT portfolio (no IRB model).

        Arrange: B31-CCR-FLOOR-2 (no IRB permission — U-TREA routes through SA).
        Act:     full Basel 3.1 pipeline.
        Assert:  u_trea == CCR_FLOOR2_GOLDEN_SFT_RWA.

        References:
            - PS1/26 Art. 92(2A): U-TREA = actual RWA for floor-eligible exposures.
        """
        # Arrange + Act — via fixture
        summary = ccr_floor2_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.u_trea == pytest.approx(CCR_FLOOR2_GOLDEN_SFT_RWA, abs=_ABS_TOL), (
            f"B31-CCR-FLOOR-2: u_trea must equal the FCCM SFT RWA for a pure-SA "
            f"portfolio (expected ≈{CCR_FLOOR2_GOLDEN_SFT_RWA:,.2f}, "
            f"got {summary.u_trea:,.2f})."
        )

    def test_b31_ccr_floor2_total_rwa_post_floor_invariant(
        self, ccr_floor2_result: AggregatedResultBundle
    ) -> None:
        """
        INVARIANT: total_rwa_post_floor == FCCM SFT RWA (no double-count).

        Floor non-binding: 0.725 × s_trea (≈9.17m) < u_trea (≈12.66m), so
        total_rwa_post_floor == u_trea. This invariant ensures the SFT RWA is
        not added to BOTH the floor numerator AND the sa_rwa_total path.

        Arrange: B31-CCR-FLOOR-2.
        Act:     full Basel 3.1 pipeline.
        Assert:  total_rwa_post_floor == CCR_FLOOR2_GOLDEN_TOTAL_RWA_POST_FLOOR.

        References:
            - PS1/26 Art. 92(2A): total = floored_modelled + sa_total + equity_total.
        """
        # Arrange + Act — via fixture
        summary = ccr_floor2_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.total_rwa_post_floor == pytest.approx(
            CCR_FLOOR2_GOLDEN_TOTAL_RWA_POST_FLOOR, abs=_ABS_TOL
        ), (
            f"B31-CCR-FLOOR-2: total_rwa_post_floor must equal the FCCM SFT RWA "
            f"(expected ≈{CCR_FLOOR2_GOLDEN_TOTAL_RWA_POST_FLOOR:,.2f}, "
            f"got {summary.total_rwa_post_floor:,.2f}). Floor non-binding; this "
            "guards against double-counting the SFT RWA in the portfolio total."
        )

    def test_b31_ccr_floor2_floor_not_binding(
        self, ccr_floor2_result: AggregatedResultBundle
    ) -> None:
        """
        portfolio_floor_binding is False (0.725 × s_trea < u_trea).

        Arrange: B31-CCR-FLOOR-2 (pure-SA FCCM SFT).
        Act:     full Basel 3.1 pipeline.
        Assert:  portfolio_floor_binding is False.

        References:
            - PS1/26 Art. 92(2A): TREA = max(U-TREA, floor_threshold).
        """
        # Arrange + Act — via fixture
        summary = ccr_floor2_result.output_floor_summary
        assert summary is not None, "Prerequisite: output_floor_summary must exist"

        # Assert
        assert summary.portfolio_floor_binding is False, (
            f"B31-CCR-FLOOR-2: portfolio_floor_binding must be False "
            f"(0.725 × s_trea < u_trea). Got "
            f"portfolio_floor_binding={summary.portfolio_floor_binding!r}, "
            f"u_trea={summary.u_trea:,.2f}, s_trea={summary.s_trea:,.2f}, "
            f"floor_threshold={summary.floor_threshold:,.2f}."
        )
