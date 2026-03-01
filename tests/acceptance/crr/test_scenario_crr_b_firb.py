"""
CRR Group B: Foundation IRB (F-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for F-IRB exposures when given fixture data as input.

Key CRR F-IRB Features:
- Bank provides own PD estimates; LGD is supervisory (CRR Art. 161)
- Senior unsecured: 45%, subordinated: 75%, financial collateral: 0%
- Single PD floor: 0.03% for all exposure classes (Art. 163)
- 1.06 scaling factor applied to all IRB exposures
- Maturity capped at [1y, 5y] (Art. 162)
- SME firm-size adjustment reduces correlation for turnover < EUR 50m (Art. 153(4))
- SME supporting factor 0.7619 for qualifying exposures (Art. 501)

Why these tests matter:
- F-IRB is the most common IRB approach for UK banks under CRR
- Supervisory LGD values are a hard constraint — incorrect LGD assignment
  directly impacts capital adequacy calculations
- The PD floor test (B6) catches a common implementation error where
  internal models assign very low PDs that violate regulatory minimums
- The maturity cap test (B7) validates that long-dated exposures don't
  produce unreasonably high capital charges

Regulatory References:
- CRR Art. 143: Permission to use IRB
- CRR Art. 153: IRB risk weight formula for non-retail
- CRR Art. 153(4): SME firm-size adjustment
- CRR Art. 161: F-IRB supervisory LGD values
- CRR Art. 162: Maturity requirements
- CRR Art. 163: PD floor (0.03%)
- CRR Art. 501: SME supporting factor
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# Mapping of scenario IDs to exposure references in fixtures
SCENARIO_EXPOSURE_MAP = {
    "CRR-B1": "LOAN_CORP_UK_001",
    "CRR-B2": "LOAN_CORP_UK_005",
    "CRR-B3": "LOAN_SUB_001",
    "CRR-B4": "LOAN_COLL_001",
    "CRR-B5": "LOAN_CORP_SME_001",
    "CRR-B6": "LOAN_CORP_UK_002",
    "CRR-B7": "LOAN_LONG_MAT_001",
}


def _get_pre_factor_rwa(result: dict[str, Any]) -> float:
    """Extract pre-supporting-factor RWA from pipeline result.

    F-IRB formula tests compare pre-factor RWA because the supporting factor
    is tested separately in CRR-F. The pipeline computes the tiered SME factor
    based on total counterparty drawn exposure (aggregated across all exposures
    to the same counterparty), which differs from per-exposure calculations.
    """
    if "rwa_pre_factor" in result and result["rwa_pre_factor"] is not None:
        return result["rwa_pre_factor"]
    sf = result.get("supporting_factor", 1.0)
    if sf and sf > 0:
        return result["rwa"] / sf
    return result["rwa"]


class TestCRRGroupB_FoundationIRB:
    """
    CRR F-IRB acceptance tests.

    Each test loads fixture data, runs it through the production calculator
    with full IRB permissions, and compares the output against pre-calculated
    expected values from the CRR workbook.

    Tests compare pre-supporting-factor RWA (the IRB formula result) to
    decouple F-IRB formula validation from the supporting factor logic.
    The supporting factor is tested separately in CRR-F.
    """

    def test_crr_b1_corporate_firb_low_pd(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B1: Corporate F-IRB with low PD (0.10%).

        Input: £25M term loan, PD 0.10%, LGD 45% (senior unsecured), ~4.25y maturity
        Expected: Standard F-IRB calculation with maturity adjustment > 1.0

        Tests the base case: supervisory LGD, moderate maturity, typical corporate.
        Low PD leads to high correlation (~0.24) and thus relatively high K per unit of EAD.
        """
        expected = expected_outputs_dict["CRR-B1"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B1"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B1",
        )

    def test_crr_b2_corporate_firb_high_pd(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B2: Corporate F-IRB with high PD (5.00%).

        Input: £5M term loan, PD 5.00%, LGD 45% (senior unsecured), ~3y maturity
        Expected: High RWA — high PD produces high K despite lower correlation

        At 5% PD, correlation drops toward 0.12 (vs ~0.24 at low PD),
        but the K formula still produces a high capital charge because the
        default probability dominates.
        """
        expected = expected_outputs_dict["CRR-B2"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B2"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B2",
        )

    def test_crr_b3_subordinated_75pct_lgd(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B3: Subordinated exposure with 75% supervisory LGD.

        Input: £2M subordinated loan, PD 1.00%, LGD 75%, ~4y maturity
        Expected: Significantly higher RWA than senior (75% vs 45% LGD)

        CRR Art. 161 requires subordinated claims to use 75% LGD.
        This test verifies the pipeline correctly assigns the higher
        supervisory LGD for subordinated seniority.
        """
        expected = expected_outputs_dict["CRR-B3"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B3"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B3",
        )

    def test_crr_b4_financial_collateral_blended_lgd(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B4: Financial collateral with blended LGD (22.5%).

        Input: £5M loan, PD 0.50%, LGD 22.5% (blended), ~2.5y maturity
        Expected: Lower RWA due to collateral-reduced LGD

        Blended LGD: 50% cash collateral at 0% + 50% unsecured at 45% = 22.5%.
        Demonstrates the capital relief from eligible financial collateral
        under the F-IRB comprehensive method.

        Note: Compares pre-factor RWA because the pipeline applies a tiered
        SME supporting factor based on total counterparty drawn exposure
        (CORP_SME_002 qualifies as SME). SF testing is in CRR-F.
        """
        expected = expected_outputs_dict["CRR-B4"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B4"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B4",
        )

    def test_crr_b5_sme_with_supporting_factor(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B5: SME corporate with firm-size adjustment and supporting factor.

        Input: £2M SME loan, PD 2.00%, LGD 45%, ~3y maturity, turnover £30M
        Expected: Reduced RWA from correlation adjustment (Art. 153(4))

        Tests the SME firm-size correlation adjustment which reduces R for
        corporates with turnover below EUR 50M. The SME supporting factor
        (Art. 501) is also applied by the pipeline but tested in CRR-F.

        Note: Compares pre-factor RWA because the pipeline computes the
        tiered SME factor based on total counterparty drawn exposure
        (includes other loans/contingents to CORP_SME_001).
        """
        expected = expected_outputs_dict["CRR-B5"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B5"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B5",
        )
        # Verify SME supporting factor is applied (< 1.0)
        sf = result.get("supporting_factor", 1.0)
        assert sf < 1.0, f"CRR-B5: SME supporting factor should be < 1.0, got {sf}"

    def test_crr_b6_pd_floor_binding(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B6: PD floor binding — internal PD 0.01% floored to 0.03%.

        Input: £1M loan, PD 0.01% (floored to 0.03%), LGD 45%, ~2y maturity
        Expected: RWA calculated using floored PD, not raw PD

        CRR Art. 163 mandates a minimum PD of 0.03% for all exposure classes.
        This test verifies that the pipeline applies the floor before calculating
        correlation, K, and maturity adjustment.
        """
        expected = expected_outputs_dict["CRR-B6"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B6"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B6",
        )
        # Verify PD floor was applied
        if "pd_floored" in result:
            assert result["pd_floored"] >= 0.0003 - 1e-8, (
                "CRR-B6: PD floor (0.03%) should be applied"
            )

    def test_crr_b7_long_maturity_capped(
        self,
        irb_only_results_df: pl.DataFrame,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """
        CRR-B7: Long maturity (7Y contractual) capped to 5Y.

        Input: £8M loan, PD 0.80%, LGD 45%, 7y maturity capped to 5y
        Expected: Maximum maturity adjustment factor (5y cap binding)

        CRR Art. 162 caps effective maturity at 5 years. Without the cap,
        the maturity adjustment would produce unreasonably high capital charges.
        This test verifies the cap is applied before the MA calculation.
        """
        expected = expected_outputs_dict["CRR-B7"]
        exposure_ref = SCENARIO_EXPOSURE_MAP["CRR-B7"]

        result = get_result_for_exposure(irb_only_results_df, exposure_ref)

        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            _get_pre_factor_rwa(result),
            expected["rwa_before_sf"],
            scenario_id="CRR-B7",
        )


class TestCRRGroupB_ParameterizedValidation:
    """
    Parametrized tests to validate expected outputs structure.
    These tests run without the production calculator.
    """

    def test_all_crr_b_scenarios_exist(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios exist in expected outputs."""
        expected_ids = [f"CRR-B{i}" for i in range(1, 8)]
        for scenario_id in expected_ids:
            assert scenario_id in expected_outputs_dict, (
                f"Missing expected output for {scenario_id}"
            )

    def test_all_crr_b_scenarios_use_firb_approach(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios use F-IRB approach."""
        for scenario in crr_b_scenarios:
            assert scenario["approach"] == "F-IRB", (
                f"Scenario {scenario['scenario_id']} should use F-IRB approach, "
                f"got {scenario['approach']}"
            )

    def test_crr_b_scenarios_have_supervisory_lgd(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify F-IRB scenarios use supervisory LGD values (not bank estimates)."""
        valid_lgds = {0.45, 0.75, 0.225, 0.0, 0.35, 0.40}
        for scenario in crr_b_scenarios:
            lgd = scenario["lgd"]
            assert lgd is not None, f"Scenario {scenario['scenario_id']} missing LGD"
            assert lgd in valid_lgds, (
                f"Scenario {scenario['scenario_id']}: LGD {lgd:.4f} is not a "
                f"valid F-IRB supervisory LGD"
            )

    def test_crr_b_pd_floor_applied(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify PD floor (0.03%) is applied in all expected outputs."""
        for scenario in crr_b_scenarios:
            pd = scenario["pd"]
            assert pd is not None and pd >= 0.0003 - 1e-8, (
                f"Scenario {scenario['scenario_id']}: PD {pd} below floor 0.03%"
            )

    def test_crr_b_rwa_positive(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all F-IRB scenarios produce positive RWA."""
        for scenario in crr_b_scenarios:
            assert scenario["rwa_after_sf"] > 0, (
                f"Scenario {scenario['scenario_id']}: RWA should be positive"
            )

    def test_crr_b5_has_supporting_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify B5 (SME) has supporting factor < 1.0."""
        b5 = expected_outputs_dict["CRR-B5"]
        assert b5["supporting_factor"] < 1.0, (
            f"CRR-B5 should have SME supporting factor < 1.0, got {b5['supporting_factor']}"
        )
        assert b5["rwa_after_sf"] < b5["rwa_before_sf"], (
            "CRR-B5: RWA after SF should be less than before SF"
        )
