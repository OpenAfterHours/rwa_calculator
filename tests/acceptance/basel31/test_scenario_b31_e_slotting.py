"""
Basel 3.1 Group E: Specialised Lending (Slotting) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for specialised lending exposures using the slotting approach
under the Basel 3.1 framework (PRA PS9/24).

Key Basel 3.1 Slotting Changes from CRR:
- Table structure: operational/pre-operational split replaces maturity split
  - CRR: 2 tables per type (>=2.5yr and <2.5yr maturity)
  - Basel 3.1: 3 tables (base/operational, PF pre-operational, HVCRE)
- PF pre-operational penalty: 80/100/120/350% (vs operational 70/90/115/250%)
- HVCRE weights: unchanged at 95/120/140/250/0%
- Base (operational non-HVCRE) weights: same as CRR >=2.5yr table

Why these tests matter:
- Slotting is the primary approach for specialised lending when A-IRB
  permission is not granted
- Basel 3.1 pre-operational PF penalty can increase capital by 14-40%
  for project finance during construction/development phase
- Current fixtures are all operational, so weights match CRR —
  the tests verify the Basel 3.1 code path produces correct results

Regulatory References:
- CRE33.5: Slotting risk weight tables
- CRE33.6: HVCRE multiplier treatment
- PRA PS9/24: UK implementation
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_risk_weight_match,
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references in fixtures
# Same exposures as CRR-E: the framework config drives different code paths
SCENARIO_EXPOSURE_MAP = {
    "B31-E1": "LOAN_SL_PF_001",
    "B31-E2": "LOAN_SL_PF_002",
    "B31-E3": "LOAN_SL_IPRE_001",
    "B31-E4": "LOAN_SL_HVCRE_001",
}


class TestB31GroupE_SlottingApproach:
    """
    Basel 3.1 slotting acceptance tests.

    Each test runs fixture data through the production calculator with
    Basel 3.1 slotting config and compares output against expected values.
    """

    def test_b31_e1_project_finance_strong(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-E1: Project Finance — Strong, operational.

        Input: £10M project finance, Strong category, operational phase
        Expected: 70% RW (same as CRR >=2.5yr non-HVCRE)

        Basel 3.1 base/operational table matches CRR >=2.5yr for Strong.
        Pre-operational PF would be 80% — but this exposure is operational.
        """
        expected = expected_outputs_dict["B31-E1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-E1"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="B31-E1",
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_before_sf"],
            scenario_id="B31-E1",
        )

    def test_b31_e2_project_finance_good(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-E2: Project Finance — Good, operational.

        Input: £10M project finance, Good category, operational phase
        Expected: 90% RW (same as CRR >=2.5yr non-HVCRE)

        Basel 3.1 pre-operational Good would be 100% — 11% penalty.
        """
        expected = expected_outputs_dict["B31-E2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-E2"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="B31-E2",
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_before_sf"],
            scenario_id="B31-E2",
        )

    def test_b31_e3_ipre_weak(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-E3: IPRE — Weak (250% punitive weight).

        Input: £5M income-producing real estate, Weak category
        Expected: 250% RW — punitive for poor-quality IPRE

        Weak category risk weight is 250% across all slotting tables
        (CRR and Basel 3.1), except Basel 3.1 pre-operational PF Weak
        which is 350%.
        """
        expected = expected_outputs_dict["B31-E3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-E3"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="B31-E3",
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_before_sf"],
            scenario_id="B31-E3",
        )

    def test_b31_e4_hvcre_strong(
        self,
        slotting_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-E4: HVCRE — Strong (95% RW).

        Input: £5M high-volatility commercial real estate, Strong category
        Expected: 95% RW — HVCRE designation uses higher weight table

        HVCRE Strong (95%) vs non-HVCRE Strong (70%) — a 36% premium
        reflecting the higher volatility of CRE exposures. HVCRE weights
        are unchanged between CRR and Basel 3.1.
        """
        expected = expected_outputs_dict["B31-E4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-E4"]

        result = get_result_for_exposure(slotting_results_df, exposure_ref)
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            expected["risk_weight"],
            scenario_id="B31-E4",
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            expected["rwa_before_sf"],
            scenario_id="B31-E4",
        )


class TestB31GroupE_FrameworkDifferences:
    """
    Cross-framework structural validation tests for slotting.

    These tests verify Basel 3.1-specific slotting properties.
    """

    def test_b31_e_all_use_slotting_approach(
        self,
        slotting_results_df: pl.DataFrame,
    ) -> None:
        """Verify all E-group exposures are routed to slotting approach."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(slotting_results_df, ref)
            if result is None:
                continue
            approach = result.get("approach", "")
            assert approach == "slotting", (
                f"{ref}: Should use slotting approach, got {approach}"
            )

    def test_b31_e_hvcre_higher_than_non_hvcre_strong(
        self,
        slotting_results_df: pl.DataFrame,
    ) -> None:
        """Verify HVCRE Strong (95%) > non-HVCRE Strong (70%)."""
        pf_strong = get_result_for_exposure(slotting_results_df, "LOAN_SL_PF_001")
        hvcre_strong = get_result_for_exposure(slotting_results_df, "LOAN_SL_HVCRE_001")

        if pf_strong is None or hvcre_strong is None:
            pytest.skip("Missing slotting results for comparison")

        assert hvcre_strong["risk_weight"] > pf_strong["risk_weight"], (
            f"HVCRE Strong ({hvcre_strong['risk_weight']}) should be > "
            f"non-HVCRE Strong ({pf_strong['risk_weight']})"
        )

    def test_b31_e_category_hierarchy_maintained(
        self,
        slotting_results_df: pl.DataFrame,
    ) -> None:
        """Verify slotting category risk weight ordering: Strong < Good < Weak."""
        e1 = get_result_for_exposure(slotting_results_df, "LOAN_SL_PF_001")
        e2 = get_result_for_exposure(slotting_results_df, "LOAN_SL_PF_002")
        e3 = get_result_for_exposure(slotting_results_df, "LOAN_SL_IPRE_001")

        if e1 is None or e2 is None or e3 is None:
            pytest.skip("Missing slotting results for comparison")

        # Strong (70%) < Good (90%) < Weak (250%)
        assert e1["risk_weight"] < e2["risk_weight"] < e3["risk_weight"], (
            f"Category hierarchy violated: Strong={e1['risk_weight']}, "
            f"Good={e2['risk_weight']}, Weak={e3['risk_weight']}"
        )

    def test_b31_e_no_pd_lgd_used_in_slotting(
        self,
        slotting_results_df: pl.DataFrame,
    ) -> None:
        """Verify slotting approach does not use PD/LGD (uses flat risk weights)."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(slotting_results_df, ref)
            if result is None:
                continue
            # Slotting RWA should be exactly EAD × RW
            expected_rwa = result["ead_final"] * result["risk_weight"]
            assert result["rwa"] == pytest.approx(expected_rwa, rel=0.001), (
                f"{ref}: Slotting RWA should be EAD × RW = "
                f"{result['ead_final']} × {result['risk_weight']} = {expected_rwa}, "
                f"got {result['rwa']}"
            )


class TestB31GroupE_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    """

    def test_all_b31_e_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-E scenarios exist in expected outputs."""
        expected_ids = [f"B31-E{i}" for i in range(1, 5)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_b31_e_scenarios_use_slotting_approach(
        self,
        b31_e_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-E scenarios use Slotting approach."""
        for scenario in b31_e_scenarios:
            assert scenario["approach"] == "Slotting", (
                f"Scenario {scenario['scenario_id']} should use Slotting approach, "
                f"got {scenario['approach']}"
            )

    def test_b31_e_valid_slotting_risk_weights(
        self,
        b31_e_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify risk weights are valid Basel 3.1 slotting values."""
        # All valid Basel 3.1 slotting risk weights
        valid_rws = {
            0.50, 0.70, 0.80, 0.90, 0.95, 1.00, 1.15, 1.20, 1.40, 2.50, 3.50, 0.00,
        }
        for scenario in b31_e_scenarios:
            rw = scenario["risk_weight"]
            assert rw in valid_rws, (
                f"Scenario {scenario['scenario_id']}: RW {rw} is not a "
                f"valid Basel 3.1 slotting risk weight"
            )

    def test_b31_e_rwa_positive(
        self,
        b31_e_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all slotting scenarios produce positive RWA."""
        for scenario in b31_e_scenarios:
            assert scenario["rwa_after_sf"] > 0, (
                f"Scenario {scenario['scenario_id']}: RWA should be positive"
            )

    def test_b31_e_no_pd_lgd_in_expected(
        self,
        b31_e_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify slotting scenarios have null PD/LGD (not used in slotting)."""
        for scenario in b31_e_scenarios:
            assert scenario["pd"] is None, (
                f"Scenario {scenario['scenario_id']}: PD should be null for slotting"
            )
            assert scenario["lgd"] is None, (
                f"Scenario {scenario['scenario_id']}: LGD should be null for slotting"
            )
