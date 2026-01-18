"""
CRR Group E: Specialised Lending Slotting Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
the slotting approach for specialised lending exposures.

Regulatory References:
- CRR Art. 153(5): Slotting approach for specialised lending
- CRR Art. 147(8): Specialised lending sub-classes
"""

import pytest
import polars as pl
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_risk_weight_match,
    get_result_for_exposure,
)


# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-E1": "LOAN_SL_PF_001",
    "CRR-E2": "LOAN_SL_PF_002",
    "CRR-E3": "LOAN_SL_IPRE_001",
    "CRR-E4": "LOAN_SL_HVCRE_001",
}


class TestCRRGroupE_SlottingApproach:
    """
    CRR Slotting acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.

    Note: CRR slotting categories differ from Basel 3.1:
    - CRR: Strong=Good=70%, Satisfactory=115%, Weak=250%
    - Basel 3.1: Strong=50%, Good=70%, Satisfactory=100%, Weak=250%
    """

    @pytest.mark.skip(reason="Fixture LOAN_SL_PF_001 not available")
    def test_crr_e1_project_finance_strong(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-E1: Project finance with Strong slotting category.

        Input: Project finance, Strong category
        Expected: 70% RW (CRR has Strong=Good=70%)

        Note: Basel 3.1 would give Strong=50%
        """
        expected = expected_outputs_dict["CRR-E1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-E1"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="CRR-E1",
        )
        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-E1",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SL_PF_002 not available")
    def test_crr_e2_project_finance_good(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-E2: Project finance with Good slotting category.

        Input: Project finance, Good category
        Expected: 70% RW (same as Strong under CRR)
        """
        expected = expected_outputs_dict["CRR-E2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-E2"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="CRR-E2",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SL_IPRE_001 not available")
    def test_crr_e3_ipre_weak(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-E3: Income-producing real estate with Weak category.

        Input: IPRE, Weak category
        Expected: 250% RW (punitive for weak credits)
        """
        expected = expected_outputs_dict["CRR-E3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-E3"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="CRR-E3",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SL_HVCRE_001 not available")
    def test_crr_e4_hvcre_strong(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-E4: HVCRE with Strong slotting category.

        Input: HVCRE, Strong category
        Expected: 70% RW (same as non-HVCRE under CRR)

        Note: Basel 3.1 applies higher RWs for HVCRE
        """
        expected = expected_outputs_dict["CRR-E4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-E4"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="CRR-E4",
        )


class TestCRRGroupE_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_e_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-E scenarios exist in expected outputs."""
        expected_ids = [f"CRR-E{i}" for i in range(1, 5)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_e_scenarios_use_slotting_approach(
        self,
        crr_e_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-E scenarios use Slotting approach."""
        for scenario in crr_e_scenarios:
            assert scenario["approach"] == "Slotting", (
                f"Scenario {scenario['scenario_id']} should use Slotting approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_e_scenarios_have_valid_slotting_rw(
        self,
        crr_e_scenarios: list[dict[str, Any]],
        crr_slotting_rw: dict,
    ) -> None:
        """Verify slotting scenarios use valid CRR risk weights."""
        valid_rws = [0.70, 1.15, 2.50, 0.00]  # Strong/Good, Satisfactory, Weak, Default
        for scenario in crr_e_scenarios:
            rw = scenario["risk_weight"]
            assert any(rw == pytest.approx(v, rel=0.01) for v in valid_rws), (
                f"Scenario {scenario['scenario_id']} has invalid slotting RW: {rw}"
            )

    def test_crr_e_strong_and_good_same_rw(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify Strong and Good have same RW under CRR (differs from Basel 3.1)."""
        strong = expected_outputs_dict["CRR-E1"]
        good = expected_outputs_dict["CRR-E2"]
        assert strong["risk_weight"] == pytest.approx(good["risk_weight"]), (
            "CRR should have Strong=Good=70%"
        )

    def test_crr_e_hvcre_same_as_non_hvcre(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify HVCRE uses same weights as non-HVCRE under CRR."""
        pf_strong = expected_outputs_dict["CRR-E1"]  # Project finance Strong
        hvcre_strong = expected_outputs_dict["CRR-E4"]  # HVCRE Strong
        assert pf_strong["risk_weight"] == pytest.approx(hvcre_strong["risk_weight"]), (
            "CRR HVCRE should use same RW as non-HVCRE (Basel 3.1 differs)"
        )
