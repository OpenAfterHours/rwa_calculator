"""
CRR Group F: Supporting Factors Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
the CRR-specific supporting factors.

Key Features:
- SME supporting factor uses TIERED approach (CRR2 Art. 501):
  - Exposures up to EUR 2.5m: factor of 0.7619 (23.81% reduction)
  - Exposures above EUR 2.5m: factor of 0.85 (15% reduction)
- Infrastructure supporting factor: 0.75 (flat, not tiered)

These factors are NOT available under Basel 3.1.

Regulatory References:
- CRR2 Art. 501: SME supporting factor (tiered)
- CRR Art. 501a: Infrastructure supporting factor
"""

import pytest
import polars as pl
from decimal import Decimal
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
    get_result_for_exposure,
)


# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-F1": "LOAN_SME_TIER1",
    "CRR-F2": "LOAN_SME_TIER_BLEND",
    "CRR-F3": "LOAN_SME_TIER2_DOM",
    "CRR-F4": "LOAN_RTL_SME_TIER1",
    "CRR-F5": "LOAN_INFRA_001",
    "CRR-F6": "LOAN_CORP_LARGE",
    "CRR-F7": "LOAN_SME_BOUNDARY",
}


class TestCRRGroupF_TieredSMEFactor:
    """
    CRR Tiered SME Supporting Factor acceptance tests.

    The SME factor is calculated as:
        factor = [min(E, threshold) * 0.7619 + max(E - threshold, 0) * 0.85] / E

    Where threshold = EUR 2.5m
    """

    @pytest.mark.skip(reason="Fixture LOAN_SME_TIER1 not available")
    def test_crr_f1_sme_tier1_only_small_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F1: Small SME exposure gets Tier 1 factor only.

        Input: Small exposure (< threshold)
        Expected: Factor = 0.7619 (pure Tier 1)
        """
        expected = expected_outputs_dict["CRR-F1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F1",
        )
        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-F1",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SME_TIER_BLEND not available")
    def test_crr_f2_sme_blended_medium_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F2: Medium SME exposure gets blended factor.

        Input: Medium exposure (above threshold)
        Expected: Blended factor between 0.7619 and 0.85
        """
        expected = expected_outputs_dict["CRR-F2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F2"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F2",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SME_TIER2_DOM not available")
    def test_crr_f3_sme_tier2_dominant_large_exposure(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F3: Large SME exposure - Tier 2 dominates.

        Input: Large exposure (well above threshold)
        Expected: Factor approaching 0.85 as Tier 2 dominates
        """
        expected = expected_outputs_dict["CRR-F3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F3"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F3",
        )

    @pytest.mark.skip(reason="Fixture LOAN_RTL_SME_TIER1 not available")
    def test_crr_f4_sme_retail_with_tiered_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F4: SME retail with tiered factor.

        Input: Retail SME exposure
        Expected: 75% RW + Tier 1 SME factor (0.7619)
        """
        expected = expected_outputs_dict["CRR-F4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F4"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F4",
        )

    @pytest.mark.skip(reason="Fixture LOAN_INFRA_001 not available")
    def test_crr_f5_infrastructure_factor_not_tiered(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F5: Infrastructure factor is NOT tiered.

        Input: Infrastructure exposure
        Expected: Flat 0.75 factor regardless of exposure size

        Note: Infrastructure factor is not tiered like SME factor
        """
        expected = expected_outputs_dict["CRR-F5"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F5"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["supporting_factor"] == pytest.approx(0.75, rel=0.001), (
            "Infrastructure factor should be 0.75"
        )

    @pytest.mark.skip(reason="Fixture LOAN_CORP_LARGE not available")
    def test_crr_f6_large_corporate_no_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F6: Large corporate (turnover > threshold) gets no SME factor.

        Input: Large exposure, high turnover
        Expected: No SME factor (turnover exceeds eligibility threshold)
        """
        expected = expected_outputs_dict["CRR-F6"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F6"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["supporting_factor"] == pytest.approx(1.0), (
            "Large corporate should have no supporting factor (1.0)"
        )

    @pytest.mark.skip(reason="Fixture LOAN_SME_BOUNDARY not available")
    def test_crr_f7_at_exposure_threshold_boundary(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-F7: Exposure exactly at threshold.

        Input: Exposure at threshold
        Expected: Factor = 0.7619 (Tier 1 includes threshold)
        """
        expected = expected_outputs_dict["CRR-F7"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-F7"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-F7",
        )


class TestCRRGroupF_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_f_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-F scenarios exist in expected outputs."""
        expected_ids = [f"CRR-F{i}" for i in range(1, 8)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_crr_f_sme_factors_in_valid_range(
        self,
        crr_f_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify SME factors are in valid range [0.7619, 1.0].

        Note: CRR-F5 is an infrastructure scenario with factor 0.75, not SME.
        """
        for scenario in crr_f_scenarios:
            sf = scenario["supporting_factor"]
            scenario_id = scenario["scenario_id"]

            # Infrastructure scenarios have factor 0.75 (not SME)
            if scenario_id == "CRR-F5":
                assert sf == pytest.approx(0.75, rel=0.001), (
                    f"Scenario {scenario_id} should have infrastructure factor 0.75, got {sf}"
                )
            else:
                assert 0.7619 <= sf <= 1.0, (
                    f"Scenario {scenario_id} has invalid supporting factor: {sf}"
                )

    def test_crr_f1_has_tier1_only_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F1 (small exposure) has Tier 1 factor."""
        scenario = expected_outputs_dict["CRR-F1"]
        assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
            "CRR-F1 should have Tier 1 factor 0.7619"
        )

    def test_crr_f2_has_blended_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F2 (medium exposure) has blended factor."""
        scenario = expected_outputs_dict["CRR-F2"]
        sf = scenario["supporting_factor"]
        # Blended factor should be between 0.7619 and 0.85
        assert 0.7619 < sf < 0.85, (
            f"CRR-F2 should have blended factor between 0.7619 and 0.85, got {sf}"
        )

    def test_crr_f3_has_tier2_dominant_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F3 (large exposure) has Tier 2 dominant factor."""
        scenario = expected_outputs_dict["CRR-F3"]
        sf = scenario["supporting_factor"]
        # Large exposure factor should be closer to 0.85
        assert sf > 0.80, (
            f"CRR-F3 should have Tier 2 dominant factor > 0.80, got {sf}"
        )

    def test_crr_f5_has_infrastructure_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F5 has flat infrastructure factor."""
        scenario = expected_outputs_dict["CRR-F5"]
        assert scenario["supporting_factor"] == pytest.approx(0.75, rel=0.001), (
            "CRR-F5 should have infrastructure factor 0.75"
        )

    def test_crr_f6_has_no_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-F6 (large corporate) has no supporting factor."""
        scenario = expected_outputs_dict["CRR-F6"]
        assert scenario["supporting_factor"] == pytest.approx(1.0), (
            "CRR-F6 should have no supporting factor (1.0)"
        )

    def test_tiered_factor_calculation_formula(
        self,
        crr_config: dict[str, Any],
    ) -> None:
        """Verify tiered factor calculation matches expected formula."""
        from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
            calculate_sme_supporting_factor,
        )

        # Test various exposure amounts
        test_cases = [
            # (exposure_gbp, expected_factor)
            (Decimal("1000000"), Decimal("0.7619")),      # Small - Tier 1 only
            (Decimal("2200000"), Decimal("0.7619")),      # At threshold
            (Decimal("4000000"), None),                    # Blended (calculate)
            (Decimal("10000000"), None),                   # Tier 2 dominant
        ]

        for exposure, expected in test_cases:
            factor = calculate_sme_supporting_factor(exposure, "GBP")
            factor_float = float(factor)
            if expected is not None:
                assert factor_float == pytest.approx(float(expected), rel=0.001), (
                    f"Factor for {exposure:,} should be {expected}, got {factor_float}"
                )
            else:
                # Just verify it's in valid range
                assert 0.7619 <= factor_float <= 0.85, (
                    f"Factor for {exposure:,} should be between 0.7619 and 0.85"
                )
