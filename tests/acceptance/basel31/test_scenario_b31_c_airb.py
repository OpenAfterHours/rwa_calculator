"""
Basel 3.1 Group C: Advanced IRB (A-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for A-IRB exposures under the Basel 3.1 framework (PRA PS9/24).

Key Basel 3.1 A-IRB Changes from CRR:
- LGD floors introduced: 25% unsecured corporate, 5% residential RE,
  10% commercial RE, 0% financial collateral (CRE30.41)
- PD floor: 0.05% corporate (was 0.03%, CRE30.55)
- Scaling factor: removed (1.0 instead of 1.06)
- Retail: still mandatory A-IRB, no maturity adjustment (CRE31.8-9)
- Specialised lending: A-IRB takes precedence over slotting when permitted

Why these tests matter:
- A-IRB LGD floors are the most impactful Basel 3.1 change for A-IRB
  banks: they set a minimum on own-estimate LGDs, which can significantly
  increase capital for low-loss portfolios
- C2 (retail) demonstrates a case where the LGD floor *increases* RWA
  relative to CRR, despite scaling factor removal
- A-IRB approach routing matters: specialised lending can use A-IRB
  instead of slotting when A-IRB permission is granted

Regulatory References:
- CRE30.41: A-IRB LGD floors by collateral type
- CRE30.55: Differentiated PD floors (0.05% corporate)
- CRE31-32: IRB risk weight formula
- CRE31.8-9: Retail A-IRB (no maturity adjustment)
- CRE33: Specialised lending approach selection
- PRA PS9/24: UK implementation, removal of scaling factor
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.basel31.conftest import (
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references in fixtures
# Same exposures as CRR-C: the framework config drives different results
SCENARIO_EXPOSURE_MAP = {
    "B31-C1": "LOAN_CORP_AIRB_001",
    "B31-C2": "LOAN_RTL_AIRB_001",
    "B31-C3": "LOAN_SL_AIRB_001",
}


def _get_pre_factor_rwa(result: dict[str, Any]) -> float:
    """Extract pre-supporting-factor RWA from pipeline result.

    Under Basel 3.1, supporting factors are disabled (SF=1.0), so
    pre-factor RWA equals final RWA. This helper maintains consistency
    with the CRR test pattern.
    """
    if "rwa_pre_factor" in result and result["rwa_pre_factor"] is not None:
        return result["rwa_pre_factor"]
    sf = result.get("supporting_factor", 1.0)
    if sf and sf > 0:
        return result["rwa"] / sf
    return result["rwa"]


class TestB31GroupC_AdvancedIRB:
    """
    Basel 3.1 A-IRB acceptance tests.

    Each test runs fixture data through the production calculator with
    Basel 3.1 full IRB config and compares output against expected values
    computed using production scalar formulas with Basel 3.1 parameters.
    """

    def test_b31_c1_corporate_airb_own_lgd_above_floor(
        self,
        airb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-C1: Corporate A-IRB with own LGD 35% (above 25% floor).

        Input: £5M term loan, PD 1.00%, LGD 35% (own estimate), ~1.0y maturity
        Expected: LGD floor (25%) does not bind — bank's own estimate used

        Demonstrates base A-IRB case where the LGD floor is non-binding.
        RWA 25% lower than CRR due to shorter relative maturity from later
        reporting date and removal of the 1.06 scaling factor.
        """
        expected = expected_outputs_dict["B31-C1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-C1"]

        result = get_result_for_exposure(airb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-C1",
        )

    def test_b31_c2_retail_airb_lgd_floor_binding(
        self,
        airb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-C2: Retail A-IRB with own LGD 15% floored to 25%.

        Input: £100k loan, PD 0.30%, LGD 15% (own estimate, floored to 25%)
        Expected: LGD floor binding — risk weight uses floored LGD 25%

        Key regulatory test: CRE30.41 mandates a 25% LGD floor for unsecured
        exposures. The bank's own estimate (15%) is below this floor, so 25%
        is used in the IRB formula. No maturity adjustment for retail (CRE31.8).

        Under CRR, there was no LGD floor, so this exposure used LGD=15%.
        Basel 3.1 RWA is 57% HIGHER than CRR for this exposure.
        """
        expected = expected_outputs_dict["B31-C2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-C2"]

        result = get_result_for_exposure(airb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-C2",
        )

    def test_b31_c3_specialised_lending_airb_over_slotting(
        self,
        airb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-C3: Specialised Lending A-IRB (project finance).

        Input: £10M project finance, PD 1.50%, LGD 25% (own estimate), ~2.5y maturity
        Expected: Routed to A-IRB (not slotting) when A-IRB permission granted

        Tests approach routing: when a bank has A-IRB permission for
        SPECIALISED_LENDING, it takes precedence over the slotting approach.
        Own LGD (25%) equals the unsecured floor — floor is at-boundary.
        """
        expected = expected_outputs_dict["B31-C3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-C3"]

        result = get_result_for_exposure(airb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-C3",
        )


class TestB31GroupC_FrameworkDifferences:
    """
    Cross-framework structural validation tests.

    These tests verify Basel 3.1-specific behavioral changes for A-IRB
    without comparing exact values — they check qualitative properties
    that distinguish Basel 3.1 A-IRB from CRR.
    """

    def test_b31_c_all_use_airb_approach(
        self,
        airb_results_df: pl.DataFrame,
    ) -> None:
        """Verify all C-group exposures are routed to A-IRB approach."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(airb_results_df, ref)
            if result is None:
                continue
            approach = result.get("approach", "")
            assert approach == "advanced_irb", (
                f"{ref}: Should use A-IRB approach, got {approach}"
            )

    def test_b31_c_lgd_floor_applied_to_retail(
        self,
        airb_results_df: pl.DataFrame,
    ) -> None:
        """Verify LGD floor is applied to retail A-IRB (C2).

        Bank's own LGD estimate is 15%, but CRE30.41 mandates a 25%
        unsecured floor. The lgd_floored column should show 25%.
        """
        result = get_result_for_exposure(airb_results_df, "LOAN_RTL_AIRB_001")
        if result is None:
            pytest.skip("LOAN_RTL_AIRB_001 not in results")

        lgd_input = result.get("lgd", result.get("lgd_input"))
        lgd_floored = result.get("lgd_floored")

        # Input LGD should be the bank's own estimate
        assert lgd_input is not None and lgd_input == pytest.approx(0.15, abs=0.01), (
            f"C2: Input LGD should be 0.15 (bank estimate), got {lgd_input}"
        )
        # Floored LGD should be 25% (unsecured floor)
        assert lgd_floored is not None and lgd_floored == pytest.approx(0.25, abs=0.01), (
            f"C2: Floored LGD should be 0.25 (unsecured floor), got {lgd_floored}"
        )

    def test_b31_c_own_lgd_preserved_when_above_floor(
        self,
        airb_results_df: pl.DataFrame,
    ) -> None:
        """Verify bank's own LGD estimate is preserved when above the floor (C1).

        C1 has LGD=35% which exceeds the 25% unsecured floor.
        Both lgd and lgd_floored should show 35%.
        """
        result = get_result_for_exposure(airb_results_df, "LOAN_CORP_AIRB_001")
        if result is None:
            pytest.skip("LOAN_CORP_AIRB_001 not in results")

        lgd = result.get("lgd")
        lgd_floored = result.get("lgd_floored")

        assert lgd is not None and lgd == pytest.approx(0.35, abs=0.01), (
            f"C1: Own LGD should be preserved at 0.35, got {lgd}"
        )
        assert lgd_floored is not None and lgd_floored == pytest.approx(0.35, abs=0.01), (
            f"C1: Floored LGD should equal own estimate 0.35, got {lgd_floored}"
        )

    def test_b31_c_no_maturity_adjustment_for_retail(
        self,
        airb_results_df: pl.DataFrame,
    ) -> None:
        """Verify retail exposure has no maturity adjustment (CRE31.8-9).

        Maturity adjustment should be 1.0 for retail exposures regardless
        of the calculated maturity value.
        """
        result = get_result_for_exposure(airb_results_df, "LOAN_RTL_AIRB_001")
        if result is None:
            pytest.skip("LOAN_RTL_AIRB_001 not in results")

        ma = result.get("maturity_adjustment", 1.0)
        assert ma == pytest.approx(1.0, abs=0.001), (
            f"C2: Retail maturity adjustment should be 1.0, got {ma}"
        )

    def test_b31_c_is_airb_flag_set(
        self,
        airb_results_df: pl.DataFrame,
    ) -> None:
        """Verify is_airb flag is True for all A-IRB exposures."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(airb_results_df, ref)
            if result is None:
                continue
            is_airb = result.get("is_airb")
            assert is_airb is True, (
                f"{ref}: is_airb should be True for A-IRB, got {is_airb}"
            )


class TestB31GroupC_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_c_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-C scenarios exist in expected outputs."""
        expected_ids = [f"B31-C{i}" for i in range(1, 4)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_b31_c_scenarios_use_airb_approach(
        self,
        b31_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-C scenarios use A-IRB approach."""
        for scenario in b31_c_scenarios:
            assert scenario["approach"] == "A-IRB", (
                f"Scenario {scenario['scenario_id']} should use A-IRB approach, "
                f"got {scenario['approach']}"
            )

    def test_b31_c_own_lgd_values_in_expected(
        self,
        b31_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify A-IRB scenarios use bank's own LGD estimates (not supervisory)."""
        # A-IRB LGDs are bank estimates, not from the fixed supervisory set
        for scenario in b31_c_scenarios:
            lgd = scenario["lgd"]
            assert lgd is not None, f"Scenario {scenario['scenario_id']} missing LGD"
            # Own estimates should be between 0 and 1
            assert 0 < lgd < 1, (
                f"Scenario {scenario['scenario_id']}: LGD {lgd} out of range"
            )

    def test_b31_c_rwa_positive(
        self,
        b31_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all A-IRB scenarios produce positive RWA."""
        for scenario in b31_c_scenarios:
            assert scenario["rwa_after_sf"] > 0, (
                f"Scenario {scenario['scenario_id']}: RWA should be positive"
            )

    def test_b31_c_supporting_factor_disabled(
        self,
        b31_c_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-C scenarios have SF=1.0 (disabled under Basel 3.1)."""
        for scenario in b31_c_scenarios:
            sf = scenario["supporting_factor"]
            assert sf == 1.0, (
                f"Scenario {scenario['scenario_id']}: SF should be 1.0 "
                f"(disabled under Basel 3.1), got {sf}"
            )
            assert scenario["rwa_before_sf"] == scenario["rwa_after_sf"], (
                f"Scenario {scenario['scenario_id']}: RWA before/after SF should "
                f"be equal when SF=1.0"
            )
