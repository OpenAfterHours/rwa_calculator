"""
CRR Group G: Provisions & Impairments Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
provisions under SA and EL shortfall/excess under IRB.

Regulatory References:
- CRR Art. 110: Provisions treatment under SA
- CRR Art. 158: Expected Loss calculation
- CRR Art. 159: Expected Loss shortfall treatment
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

from typing import Any

import polars as pl
import pytest
from tests.acceptance.crr.conftest import (
    assert_ead_match,
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-G1": "LOAN_PROV_G1",
    "CRR-G2": "LOAN_PROV_G2",
    "CRR-G3": "LOAN_PROV_G3",
}


class TestCRRGroupG_Provisions:
    """
    CRR Provisions acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    def test_crr_g1_sa_with_specific_provision(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G1: SA exposure with specific provision reduces EAD.

        Input: Gross exposure, specific provision
        Expected: EAD = gross - provision (net of provision)

        CRR Art. 110: Specific provisions reduce exposure value
        """
        expected = expected_outputs_dict["CRR-G1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_ead_match(
            result["ead_final"],
            expected["ead"],
            scenario_id="CRR-G1",
        )

    def test_crr_g2_irb_el_shortfall(
        self,
        irb_pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G2: IRB EL shortfall results in CET1/T2 deduction.

        Input: EL > Total provisions
        Expected: Shortfall = EL - provisions, 50% deducted from CET1, 50% from T2

        CRR Art. 159: Shortfall treatment
        """
        expected = expected_outputs_dict["CRR-G2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G2"]

        result = get_result_for_exposure(irb_pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-G2",
        )

    def test_crr_g3_irb_el_excess(
        self,
        irb_pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-G3: IRB EL excess can be added to T2 capital (capped).

        Input: EL < Total provisions
        Expected: Excess = provisions - EL, T2 credit capped at 0.6% of IRB RWA

        CRR Art. 62(d): Excess provisions as T2 (capped at 0.6% IRB RWA)
        """
        expected = expected_outputs_dict["CRR-G3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-G3"]

        result = get_result_for_exposure(irb_pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-G3",
        )


class TestCRRGroupG_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_g_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-G scenarios exist in expected outputs."""
        expected_ids = ["CRR-G1", "CRR-G2", "CRR-G3"]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_crr_g1_uses_sa_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-G1 (SA provision) uses SA approach."""
        scenario = expected_outputs_dict["CRR-G1"]
        assert scenario["approach"] == "SA", "CRR-G1 should use SA approach"

    def test_crr_g2_g3_use_firb_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-G2 and G3 (EL shortfall/excess) use F-IRB approach."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["approach"] == "F-IRB", f"{scenario_id} should use F-IRB approach"

    def test_crr_g_irb_scenarios_have_expected_loss(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify IRB provision scenarios have expected loss calculated."""
        for scenario_id in ["CRR-G2", "CRR-G3"]:
            scenario = expected_outputs_dict[scenario_id]
            assert scenario["expected_loss"] is not None, f"{scenario_id} should have expected loss"
            assert scenario["expected_loss"] > 0, (
                f"{scenario_id} should have positive expected loss"
            )
