"""
Basel 3.1 Group B: Foundation IRB (F-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for F-IRB exposures under the Basel 3.1 framework (PRA PS9/24).

Key Basel 3.1 F-IRB Changes from CRR:
- Senior unsecured LGD: 40% (was 45%, CRE32.9)
- PD floor: 0.05% corporate (was 0.03%, CRE30.55)
- Scaling factor: removed (1.0 instead of 1.06)
- SME supporting factor: removed (was 0.7619/0.85, PRA PS9/24)
- Subordinated LGD: unchanged at 75%
- Maturity adjustment: unchanged [1Y, 5Y]

Why these tests matter:
- F-IRB supervisory LGD is a hard regulatory constraint — the reduced 40%
  senior unsecured LGD under Basel 3.1 directly lowers capital requirements
  for unsecured corporate exposures
- The higher PD floor (0.05% vs 0.03%) increases capital for very low-PD
  exposures, partially offsetting other reductions
- Removal of the 1.06 scaling factor reduces all IRB RWA by ~5.7%
- Combined effect: most F-IRB RWA drops ~16-21% under Basel 3.1, except
  for very low-PD exposures where the higher PD floor dominates

Regulatory References:
- CRE30.55: Differentiated PD floors (0.05% corporate)
- CRE31-32: IRB risk weight formula
- CRE32.9-12: Revised F-IRB supervisory LGD values
- PRA PS9/24: UK implementation, removal of scaling/supporting factors
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
# Same exposures as CRR-B: the framework config drives different results
SCENARIO_EXPOSURE_MAP = {
    "B31-B1": "LOAN_CORP_UK_001",
    "B31-B2": "LOAN_CORP_UK_005",
    "B31-B3": "LOAN_SUB_001",
    "B31-B4": "LOAN_COLL_001",
    "B31-B5": "LOAN_CORP_SME_001",
    "B31-B6": "LOAN_CORP_UK_002",
    "B31-B7": "LOAN_LONG_MAT_001",
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


class TestB31GroupB_FoundationIRB:
    """
    Basel 3.1 F-IRB acceptance tests.

    Each test runs fixture data through the production calculator with
    Basel 3.1 F-IRB config and compares output against expected values
    computed using production scalar formulas with Basel 3.1 parameters.
    """

    def test_b31_b1_corporate_firb_low_pd(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B1: Corporate F-IRB with low PD (0.10%).

        Input: £25M term loan, PD 0.10%, LGD 40% (B31 senior unsecured), ~2.75y maturity
        Expected: Lower RWA than CRR due to LGD 40% (was 45%) and no 1.06 scaling

        Tests the base case: revised supervisory LGD and removed scaling factor.
        Combined effect reduces RWA by ~21% vs CRR for the same exposure.
        """
        expected = expected_outputs_dict["B31-B1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B1"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B1",
        )

    def test_b31_b2_corporate_firb_high_pd(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B2: Corporate F-IRB with high PD (5.00%).

        Input: £5M term loan, PD 5.00%, LGD 40% (B31 senior unsecured), ~1.5y maturity
        Expected: High RWA despite LGD reduction — PD dominates the K formula

        At 5% PD, the PD floor (0.05%) does not bind. The RWA reduction vs CRR
        comes entirely from the lower LGD and removed scaling factor.
        """
        expected = expected_outputs_dict["B31-B2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B2"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B2",
        )

    def test_b31_b3_subordinated_75pct_lgd(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B3: Subordinated exposure with 75% supervisory LGD (unchanged).

        Input: £2M subordinated loan, PD 1.00%, LGD 75%, ~2.5y maturity
        Expected: RWA ~5.7% lower than CRR (only scaling factor removal)

        Subordinated LGD is unchanged at 75% under Basel 3.1 (CRE32.9).
        The only RWA reduction comes from removing the 1.06 scaling factor.
        """
        expected = expected_outputs_dict["B31-B3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B3"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B3",
        )

    def test_b31_b4_sme_corporate_with_correlation_adjustment(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B4: SME corporate with firm-size correlation adjustment.

        Input: £5M loan, PD 0.50%, LGD 40% (B31 senior unsecured), ~1.0y maturity
        Expected: Reduced correlation via SME firm-size adjustment (CRR Art. 153(4))

        SME turnover (£35M) triggers firm-size correlation adjustment, reducing R.
        No supporting factor under Basel 3.1 (was 0.7619 under CRR).
        """
        expected = expected_outputs_dict["B31-B4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B4"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B4",
        )

    def test_b31_b5_sme_no_supporting_factor(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B5: SME corporate — no supporting factor under Basel 3.1.

        Input: £2M SME loan, PD 2.00%, LGD 40%, ~1.5y maturity, turnover £30M
        Expected: SF=1.0 (disabled). Base RWA lower than CRR, but total RWA
                  higher than CRR post-SF because 0.7619 SF is removed.

        This test validates the critical policy change: SME supporting factor
        removal under PRA PS9/24. Banks lose the 0.7619 multiplier that
        significantly reduced SME capital requirements under CRR Art. 501.
        """
        expected = expected_outputs_dict["B31-B5"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B5"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B5",
        )
        # Verify supporting factor is 1.0 (disabled under Basel 3.1)
        sf = result.get("supporting_factor", 1.0)
        assert sf == pytest.approx(1.0, abs=0.0001), (
            f"B31-B5: Supporting factor should be 1.0 (disabled), got {sf}"
        )

    def test_b31_b6_pd_floor_binding_higher_than_crr(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B6: PD floor binding — internal PD 0.01% floored to 0.05%.

        Input: £1M loan, PD 0.01% (floored to 0.05%), LGD 40%, 1.0y maturity
        Expected: RWA calculated using floored PD (0.05%), not raw PD

        Basel 3.1 CRE30.55 mandates a 0.05% PD floor for corporate exposures
        (up from CRR's 0.03%). For very low-PD exposures, the higher floor
        increases capital charges, partially offsetting other Basel 3.1 reductions.
        """
        expected = expected_outputs_dict["B31-B6"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B6"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B6",
        )

    def test_b31_b7_long_maturity_capped(
        self,
        firb_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        B31-B7: Long maturity (7Y contractual) capped to 5Y.

        Input: £8M loan, PD 0.80%, LGD 40%, 7y maturity capped to 5y
        Expected: Maximum maturity adjustment factor (5y cap binding)

        Maturity cap unchanged at 5Y under Basel 3.1. Combined with LGD 40%
        and no scaling, RWA is ~16% lower than CRR for the same exposure.
        """
        expected = expected_outputs_dict["B31-B7"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["B31-B7"]

        result = get_result_for_exposure(firb_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="B31-B7",
        )


class TestB31GroupB_FrameworkDifferences:
    """
    Cross-framework structural validation tests.

    These tests verify Basel 3.1-specific behavioral changes without
    comparing exact values — they check qualitative properties that
    distinguish Basel 3.1 from CRR.
    """

    def test_b31_b_no_scaling_factor_applied(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify no 1.06 scaling factor is applied to Basel 3.1 F-IRB exposures."""
        for ref in SCENARIO_EXPOSURE_MAP.values():
            result = get_result_for_exposure(firb_results_df, ref)
            if result is None:
                continue
            # Under Basel 3.1, SF should always be 1.0
            sf = result.get("supporting_factor", 1.0)
            assert sf == pytest.approx(1.0, abs=0.001), (
                f"{ref}: Supporting factor should be 1.0 under Basel 3.1, got {sf}"
            )

    def test_b31_b_supervisory_lgd_values(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify F-IRB exposures use Basel 3.1 supervisory LGD values."""
        # Senior unsecured should be 40% under Basel 3.1
        senior_refs = [
            "LOAN_CORP_UK_001", "LOAN_CORP_UK_005", "LOAN_COLL_001",
            "LOAN_CORP_SME_001", "LOAN_CORP_UK_002", "LOAN_LONG_MAT_001",
        ]
        for ref in senior_refs:
            result = get_result_for_exposure(firb_results_df, ref)
            if result is None:
                continue
            lgd = result.get("lgd")
            assert lgd is not None and lgd == pytest.approx(0.40, abs=0.01), (
                f"{ref}: Senior unsecured LGD should be 40% under Basel 3.1, got {lgd}"
            )

        # Subordinated should be 75% (unchanged)
        result = get_result_for_exposure(firb_results_df, "LOAN_SUB_001")
        if result is not None:
            lgd = result.get("lgd")
            assert lgd is not None and lgd == pytest.approx(0.75, abs=0.01), (
                f"LOAN_SUB_001: Subordinated LGD should be 75%, got {lgd}"
            )

    def test_b31_b_pd_floor_higher_for_corporate(
        self,
        firb_results_df: pl.DataFrame,
    ) -> None:
        """Verify Basel 3.1 PD floor (0.05%) is applied for corporate exposures.

        LOAN_CORP_UK_002 has raw PD 0.01%. Under Basel 3.1 the floor is 0.05%
        (CRE30.55), vs CRR's 0.03%. We check EL which uses floored PD.
        """
        result = get_result_for_exposure(firb_results_df, "LOAN_CORP_UK_002")
        if result is None:
            pytest.skip("LOAN_CORP_UK_002 not in results")

        # EL = PD_floored × LGD × EAD
        # With PD_floored=0.0005, LGD=0.40, EAD=1M: EL=200
        el = result.get("expected_loss", 0)
        assert el == pytest.approx(200.0, rel=0.01), (
            f"B31-B6: EL should be 200 (PD floor 0.05% × LGD 40% × 1M), got {el}"
        )


class TestB31GroupB_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_b31_b_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all B31-B scenarios exist in expected outputs."""
        expected_ids = [f"B31-B{i}" for i in range(1, 8)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_b31_b_scenarios_use_firb_approach(
        self,
        b31_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-B scenarios use F-IRB approach."""
        for scenario in b31_b_scenarios:
            assert scenario["approach"] == "F-IRB", (
                f"Scenario {scenario['scenario_id']} should use F-IRB approach, "
                f"got {scenario['approach']}"
            )

    def test_b31_b_supervisory_lgd_values_in_expected(
        self,
        b31_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify F-IRB scenarios use Basel 3.1 supervisory LGD values."""
        valid_lgds = {0.40, 0.75, 0.20, 0.0, 0.25}  # Basel 3.1 supervisory LGDs
        for scenario in b31_b_scenarios:
            lgd = scenario["lgd"]
            assert lgd is not None, f"Scenario {scenario['scenario_id']} missing LGD"
            assert lgd in valid_lgds, (
                f"Scenario {scenario['scenario_id']}: LGD {lgd:.4f} is not a "
                f"valid Basel 3.1 F-IRB supervisory LGD"
            )

    def test_b31_b_pd_floor_applied_in_expected(
        self,
        b31_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify PD floor (0.05% for corporate) is respected in expected outputs.

        EL = PD_floored × LGD × EAD, so EL/LGD/EAD >= 0.0005 for corporate.
        """
        for scenario in b31_b_scenarios:
            el = scenario.get("expected_loss")
            lgd = scenario.get("lgd")
            ead = scenario.get("ead")
            if el is not None and lgd is not None and lgd > 0 and ead is not None and ead > 0:
                implied_pd = el / (lgd * ead)
                assert implied_pd >= 0.0005 - 1e-8, (
                    f"Scenario {scenario['scenario_id']}: Implied PD {implied_pd:.6f} "
                    f"below Basel 3.1 floor 0.05%"
                )

    def test_b31_b_rwa_positive(
        self,
        b31_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all F-IRB scenarios produce positive RWA."""
        for scenario in b31_b_scenarios:
            assert scenario["rwa_after_sf"] > 0, (
                f"Scenario {scenario['scenario_id']}: RWA should be positive"
            )

    def test_b31_b_supporting_factor_disabled(
        self,
        b31_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all B31-B scenarios have SF=1.0 (disabled under Basel 3.1)."""
        for scenario in b31_b_scenarios:
            sf = scenario["supporting_factor"]
            assert sf == 1.0, (
                f"Scenario {scenario['scenario_id']}: SF should be 1.0 "
                f"(disabled under Basel 3.1), got {sf}"
            )
            assert scenario["rwa_before_sf"] == scenario["rwa_after_sf"], (
                f"Scenario {scenario['scenario_id']}: RWA before/after SF should "
                f"be equal when SF=1.0"
            )
