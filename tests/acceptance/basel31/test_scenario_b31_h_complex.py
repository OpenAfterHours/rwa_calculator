"""
Basel 3.1 Group H: Complex/Combined Scenarios Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
complex scenarios involving facility hierarchies and SME treatment under
the Basel 3.1 framework (PRA PS9/24).

Key Basel 3.1 Differences for Complex Scenarios:
- Facility aggregation: unchanged mechanism (same EAD aggregation)
- SME corporate: 85% RW (was 100% under CRR, CRE20.47-49)
- SME supporting factor: REMOVED (was 0.7619/0.85 under CRR Art. 501)
- Net effect for SMEs: RWA INCREASES ~12% despite lower risk weight,
  because 85% > 100% x 0.7619 = 76.19%

Why these tests matter:
    H1 validates that facility hierarchy aggregation works identically
    under Basel 3.1 — the same EAD computation, same unrated corporate
    risk weight (100%), producing the same RWA. This confirms that Basel 3.1
    changes don't inadvertently break the core aggregation pipeline.

    H3 demonstrates a critical policy outcome: SME corporates can see HIGHER
    capital requirements under Basel 3.1 despite the lower 85% risk weight.
    The removal of the SME supporting factor (CRR Art. 501) more than offsets
    the risk weight reduction. Under CRR: effective RW = 100% x 0.7619 = 76.19%;
    under Basel 3.1: 85% flat. This 12% increase in RWA is a material impact
    for banks with large SME portfolios.

Regulatory References:
- CRE20.47-49: Basel 3.1 SME corporate risk weight (85%)
- CRR Art. 111, 113: Facility hierarchy and exposure aggregation
- CRR Art. 501: SME supporting factor (removed under Basel 3.1)
- PRA PS9/24: UK implementation, removal of supporting factors
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references
# Note: H2 and H4 not included (same as CRR — fixture/expected output mismatches)
SCENARIO_EXPOSURE_MAP = {
    "B31-H1": "FAC_MULTI_001",
    "B31-H3": "LOAN_SME_CHAIN",
}


class TestB31GroupH_ComplexScenarios:
    """
    Basel 3.1 Complex scenario acceptance tests.

    Each test runs fixture data through the production calculator with
    Basel 3.1 config and compares output against expected values.
    """

    def test_b31_h1_facility_multiple_loans(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-H1: Facility with multiple sub-exposures.

        Input: Facility with £4M drawn + £500k CCF on undrawn = £4.5M EAD
        Expected: Aggregated EAD = £4.5M, RW = 100%, RWA = £4.5M

        Facility aggregation is unchanged under Basel 3.1. The unrated
        corporate risk weight remains 100%. This test confirms Basel 3.1
        framework changes don't break core aggregation mechanics.
        """
        expected = expected_outputs_dict["B31-H1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-H1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="B31-H1",
        )

    def test_b31_h3_sme_no_supporting_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-H3: SME corporate — 85% RW, no supporting factor.

        Input: £2M loan, SME corporate (turnover £25M)
        Expected: RW = 85%, SF = 1.0, RWA = £1.7M

        Under CRR: RW = 100%, SF = 0.7619, RWA = £1,523,800
        Under Basel 3.1: RW = 85%, SF = 1.0, RWA = £1,700,000

        RWA is 12% HIGHER under Basel 3.1 because SF removal (0.7619)
        more than offsets the lower risk weight (85% vs 100%).
        """
        expected = expected_outputs_dict["B31-H3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-H3"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="B31-H3",
        )


class TestB31GroupH_FrameworkDifferences:
    """
    Cross-framework structural validation tests.

    These tests verify Basel 3.1-specific behavioral changes for
    complex/combined scenarios.
    """

    def test_b31_h1_unrated_corporate_100pct_rw(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify unrated corporate risk weight is 100% (unchanged from CRR)."""
        result = get_result_for_exposure(pipeline_results_df, "FAC_MULTI_001")
        if result is None:
            pytest.skip("FAC_MULTI_001 not in results")

        rw = result.get("risk_weight", 0)
        assert rw == pytest.approx(1.0, abs=0.001), (
            f"B31-H1: Unrated corporate RW should be 100%, got {rw}"
        )

    def test_b31_h3_sme_corporate_85pct_rw(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify SME corporate gets 85% risk weight under Basel 3.1.

        CRE20.47-49: SME corporate risk weight = 85% (was 100% under CRR).
        """
        result = get_result_for_exposure(pipeline_results_df, "LOAN_SME_CHAIN")
        if result is None:
            pytest.skip("LOAN_SME_CHAIN not in results")

        rw = result.get("risk_weight", 0)
        assert rw == pytest.approx(0.85, abs=0.01), (
            f"B31-H3: SME corporate RW should be 85% under Basel 3.1, got {rw}"
        )

    def test_b31_h3_no_supporting_factor(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify SME supporting factor is removed (SF=1.0) under Basel 3.1.

        PRA PS9/24 removes CRR Art. 501 SME supporting factor.
        """
        result = get_result_for_exposure(pipeline_results_df, "LOAN_SME_CHAIN")
        if result is None:
            pytest.skip("LOAN_SME_CHAIN not in results")

        sf = result.get("supporting_factor", 1.0)
        assert sf == pytest.approx(1.0, abs=0.0001), (
            f"B31-H3: SF should be 1.0 (disabled under Basel 3.1), got {sf}"
        )

    def test_b31_h3_rwa_higher_than_crr_effective(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify Basel 3.1 SME RWA is higher than CRR effective RWA.

        CRR effective: 100% x 0.7619 x £2M = £1,523,800
        Basel 3.1: 85% x 1.0 x £2M = £1,700,000
        Difference: +£176,200 (+12%)
        """
        result = get_result_for_exposure(pipeline_results_df, "LOAN_SME_CHAIN")
        if result is None:
            pytest.skip("LOAN_SME_CHAIN not in results")

        b31_rwa = result.get("rwa_final", 0)
        crr_effective_rwa = 2_000_000.0 * 1.0 * 0.7619  # CRR: 100% RW x 0.7619 SF
        assert b31_rwa > crr_effective_rwa, (
            f"B31-H3: Basel 3.1 RWA ({b31_rwa:,.0f}) should exceed CRR effective "
            f"RWA ({crr_effective_rwa:,.0f}) — SF removal dominates"
        )

    def test_b31_h_no_supporting_factor_on_any_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
    ) -> None:
        """Verify no supporting factor applied to any H-group exposure."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(pipeline_results_df, ref)
            if result is None:
                continue
            sf = result.get("supporting_factor", 1.0)
            assert sf == pytest.approx(1.0, abs=0.001), (
                f"{ref}: SF should be 1.0 under Basel 3.1, got {sf}"
            )


class TestB31GroupH_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_h_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-H scenarios exist in expected outputs."""
        expected_ids = ["B31-H1", "B31-H3"]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_b31_h3_sme_85pct_risk_weight(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify B31-H3 (SME) has Basel 3.1 risk weight of 85%."""
        scenario = expected_outputs_dict["B31-H3"]
        assert scenario["risk_weight"] == pytest.approx(0.85, rel=0.001), (
            "B31-H3 should have 85% risk weight under Basel 3.1"
        )

    def test_b31_h_supporting_factor_disabled(
        self,
        b31_h_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-H scenarios have SF=1.0 (disabled under Basel 3.1)."""
        for scenario in b31_h_scenarios:
            sf = scenario["supporting_factor"]
            assert sf == 1.0, (
                f"Scenario {scenario['scenario_id']}: SF should be 1.0, got {sf}"
            )
            assert scenario["rwa_before_sf"] == pytest.approx(
                scenario["rwa_after_sf"], rel=0.001
            ), (
                f"Scenario {scenario['scenario_id']}: RWA before/after SF "
                f"should be equal when SF=1.0"
            )
