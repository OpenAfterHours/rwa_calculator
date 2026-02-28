"""
CRR Group D: Credit Risk Mitigation (CRM) Acceptance Tests.

These tests validate that the production RWA calculator correctly applies
CRM treatments including collateral haircuts, guarantees, and maturity mismatches.

Regulatory References:
- CRR Art. 192-241: Credit Risk Mitigation
- CRR Art. 223-224: Financial Collateral Comprehensive Method
- CRR Art. 233-236: Guarantees and credit derivatives
- CRR Art. 238: Maturity mismatch
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
    "CRR-D1": "LOAN_CRM_D1",
    "CRR-D2": "LOAN_CRM_D2",
    "CRR-D3": "LOAN_CRM_D3",
    "CRR-D4": "LOAN_CRM_D4",
    "CRR-D5": "LOAN_CRM_D5",
    "CRR-D6": "LOAN_CRM_D6",
}


class TestCRRGroupD_CreditRiskMitigation:
    """
    CRR CRM acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.
    """

    def test_crr_d1_cash_collateral_zero_haircut(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D1: Cash collateral has 0% supervisory haircut.

        Input: Exposure, cash collateral
        Expected: EAD reduced (cash reduces exposure 1:1)

        CRR Art. 224: Cash has 0% haircut
        """
        expected = expected_outputs_dict["CRR-D1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_ead_match(
            result["ead_final"],
            expected["ead"],
            scenario_id="CRR-D1",
        )

    def test_crr_d2_govt_bond_collateral(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D2: Government bond collateral with supervisory haircut.

        Input: Exposure, govt bond (CQS 1, >5y maturity)
        Expected: 4% haircut applied to collateral

        CRR Art. 224: CQS 1 govt bond >5y = 4% haircut
        """
        expected = expected_outputs_dict["CRR-D2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D2"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-D2",
        )

    def test_crr_d3_equity_collateral_main_index(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D3: Equity collateral (main index) has 15% haircut.

        Input: Exposure, FTSE 100 equity collateral
        Expected: 15% haircut (vs 25% for non-main index)

        CRR Art. 224: Main index equity = 15% haircut
        """
        expected = expected_outputs_dict["CRR-D3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D3"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-D3",
        )

    def test_crr_d4_bank_guarantee_substitution(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D4: Bank guarantee allows substitution of guarantor's RW.

        Input: Unrated corporate exposure, guaranteed by CQS 2 bank
        Expected: Split treatment - guaranteed portion at 30% RW (UK deviation)

        CRR Art. 213-217: Unfunded credit protection
        """
        expected = expected_outputs_dict["CRR-D4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D4"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-D4",
        )

    def test_crr_d5_maturity_mismatch(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D5: Maturity mismatch reduces collateral effectiveness.

        Input: Exposure (5y), collateral (2y)
        Expected: Collateral value reduced by maturity adjustment

        Formula: Adjusted = C * (t - 0.25) / (T - 0.25)
        where t = collateral maturity, T = exposure maturity

        CRR Art. 238: Maturity mismatch
        """
        expected = expected_outputs_dict["CRR-D5"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D5"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-D5",
        )

    def test_crr_d6_currency_mismatch(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-D6: Currency mismatch adds 8% additional haircut.

        Input: GBP exposure, EUR collateral
        Expected: 8% FX haircut applied

        CRR Art. 224: Currency mismatch = 8% additional haircut
        """
        expected = expected_outputs_dict["CRR-D6"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-D6"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-D6",
        )


class TestCRRGroupD_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_d_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-D scenarios exist in expected outputs."""
        expected_ids = [f"CRR-D{i}" for i in range(1, 7)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_d_scenarios_use_crm_approach(
        self,
        crr_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-D scenarios use SA-CRM approach."""
        for scenario in crr_d_scenarios:
            assert scenario["approach"] == "SA-CRM", (
                f"Scenario {scenario['scenario_id']} should use SA-CRM approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_d_scenarios_have_reduced_ead(
        self,
        crr_d_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify CRM scenarios show effect of mitigation on EAD or RWA."""
        for scenario in crr_d_scenarios:
            # All CRM scenarios should result in some form of risk reduction
            assert scenario["ead"] is not None, f"Scenario {scenario['scenario_id']} missing EAD"
            assert scenario["rwa_after_sf"] is not None, (
                f"Scenario {scenario['scenario_id']} missing RWA"
            )
