"""
CRR Group H: Complex/Combined Scenarios Acceptance Tests.

These tests validate that the production RWA calculator correctly handles
complex scenarios involving multiple features, hierarchies, and combined treatments.

Regulatory References:
- CRR Art. 111, 113: Facility hierarchy and aggregation
- CRR Art. 142: Counterparty group and rating inheritance
- CRR Art. 501: SME supporting factor chain
- CRR Art. 207-236: Combined CRM treatments
"""

import pytest
import polars as pl
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
    get_result_for_exposure,
)


# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-H1": "FAC_MULTI_001",
    "CRR-H2": "GRP_MULTI_001",
    "CRR-H3": "LOAN_SME_CHAIN",
    "CRR-H4": "LOAN_CRM_FULL",
}


class TestCRRGroupH_ComplexScenarios:
    """
    CRR Complex scenario acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.

    These tests verify that the calculator correctly handles:
    - Multi-exposure facilities
    - Counterparty hierarchies and rating inheritance
    - Combined SME adjustments
    - Chained CRM treatments
    """

    @pytest.mark.skip(reason="Fixture FAC_MULTI_001 not available")
    def test_crr_h1_facility_multiple_loans(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-H1: Facility with multiple sub-exposures.

        Input: Facility containing term loan, trade finance, overdraft, undrawn commitment
        Expected: Aggregated EAD across sub-exposures

        Tests correct aggregation of exposures within facility hierarchy.
        """
        expected = expected_outputs_dict["CRR-H1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-H1"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-H1",
        )

    @pytest.mark.skip(reason="Fixture GRP_MULTI_001 not available")
    def test_crr_h2_counterparty_group_rating_inheritance(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-H2: Counterparty group with rating inheritance.

        Input: Group with:
          - Parent: CQS 2
          - Sub1: unrated (inherits parent CQS 2)
          - Sub2: CQS 3 (uses own rating)
        Expected: Blended RW based on inheritance rules

        CRR Art. 142: Rating inheritance within groups
        """
        expected = expected_outputs_dict["CRR-H2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-H2"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-H2",
        )

    @pytest.mark.skip(reason="Fixture LOAN_SME_CHAIN not available")
    def test_crr_h3_sme_chain_supporting_factor(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-H3: SME chain with supporting factor.

        Input: Loan, SME counterparty
        Expected: RWA reduced by SME supporting factor (0.7619)

        Effective RW = 100% * 0.7619 = 76.19%
        """
        expected = expected_outputs_dict["CRR-H3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-H3"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_supporting_factor_match(
            result["supporting_factor"],
            expected["supporting_factor"],
            scenario_id="CRR-H3",
        )
        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-H3",
        )

    @pytest.mark.skip(reason="Fixture LOAN_CRM_FULL not available")
    def test_crr_h4_full_crm_chain(
        self,
        pipeline_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-H4: Full CRM chain - collateral + guarantee + provision.

        Input: Gross exposure with:
          - Specific provision
          - Cash collateral
          - Bank guarantee
        Expected: RWA significantly reduced through combined CRM

        Tests correct ordering and application of multiple CRM techniques.
        """
        expected = expected_outputs_dict["CRR-H4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-H4"]

        result = get_result_for_exposure(pipeline_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa_final"],
            expected["rwa_after_sf"],
            scenario_id="CRR-H4",
        )


class TestCRRGroupH_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_h_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-H scenarios exist in expected outputs."""
        expected_ids = [f"CRR-H{i}" for i in range(1, 5)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_crr_h3_has_sme_supporting_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-H3 (SME chain) has supporting factor applied."""
        scenario = expected_outputs_dict["CRR-H3"]
        assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
            "CRR-H3 should have SME supporting factor 0.7619"
        )

    def test_crr_h4_uses_crm_approach(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-H4 (full CRM chain) uses SA-CRM approach."""
        scenario = expected_outputs_dict["CRR-H4"]
        assert scenario["approach"] == "SA-CRM", (
            "CRR-H4 should use SA-CRM approach"
        )

    def test_crr_h4_shows_crm_reduction(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-H4 demonstrates RWA reduction from CRM chain."""
        scenario = expected_outputs_dict["CRR-H4"]
        # Gross at 100% RW would be a high RWA without CRM
        # With CRM chain, should be significantly lower
        gross_rwa = 2_000_000.0
        actual_rwa = scenario["rwa_after_sf"]
        reduction = (gross_rwa - actual_rwa) / gross_rwa
        assert reduction > 0.3, (
            f"CRR-H4 should show significant RWA reduction from CRM, got {reduction*100:.1f}%"
        )
