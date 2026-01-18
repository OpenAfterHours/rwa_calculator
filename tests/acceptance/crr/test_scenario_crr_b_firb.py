"""
CRR Group B: Foundation IRB (F-IRB) Acceptance Tests.

These tests validate that the production RWA calculator produces correct
outputs for F-IRB exposures when given fixture data as input.

Regulatory References:
- CRR Art. 153: IRB risk weight formula
- CRR Art. 161: Supervisory LGD values (45% senior, 75% subordinated)
- CRR Art. 162: Maturity (1-5 year floor/cap)
- CRR Art. 163: PD floor (0.03% single floor)
- CRR Art. 153(4): SME firm size adjustment
- CRR Art. 501: SME supporting factor (0.7619)
"""

import pytest
import polars as pl
from typing import Any

from tests.acceptance.crr.conftest import (
    assert_rwa_within_tolerance,
    assert_risk_weight_match,
    assert_ead_match,
    assert_supporting_factor_match,
    get_result_for_exposure,
)


# Mapping of scenario IDs to exposure references
SCENARIO_EXPOSURE_MAP = {
    "CRR-B1": "LOAN_CORP_UK_001",
    "CRR-B2": "LOAN_CORP_UK_005",
    "CRR-B3": "LOAN_SUB_001",
    "CRR-B4": "LOAN_COLL_001",
    "CRR-B5": "LOAN_CORP_SME_001",
    "CRR-B6": "LOAN_CORP_UK_002",
    "CRR-B7": "LOAN_LONG_MAT_001",
}


def _get_actual_result(
    irb_only_results_df: pl.DataFrame,
    exposure_reference: str,
    scenario_id: str,
) -> dict[str, Any]:
    """
    Get actual pipeline result and validate it exists with required IRB fields.

    Raises AssertionError with clear message if exposure not found or
    IRB calculation incomplete (pd/rwa missing). This ensures mismatches
    between expected outputs and pipeline results are clearly visible.
    """
    actual = get_result_for_exposure(irb_only_results_df, exposure_reference)
    assert actual is not None, (
        f"{scenario_id}: Exposure {exposure_reference} not found in IRB pipeline results. "
        f"Check that the loan exists in fixtures and the pipeline processes it."
    )

    # Check if IRB calculation was completed (pd and rwa must be populated)
    assert actual.get("pd") is not None, (
        f"{scenario_id}: Exposure {exposure_reference} found but PD is None. "
        f"Check that the counterparty has an internal rating in fixtures."
    )
    assert actual.get("rwa") is not None, (
        f"{scenario_id}: Exposure {exposure_reference} found with PD={actual['pd']} but RWA is None. "
        f"Check IRB calculation logic."
    )
    return actual


class TestCRRGroupB_FoundationIRB:
    """
    CRR F-IRB acceptance tests.

    Each test loads fixture data, runs it through the production calculator,
    and compares the output against pre-calculated expected values.

    Note: F-IRB only applies to wholesale exposures (corporate, institution,
    sovereign). Retail exposures require A-IRB or Standardised Approach.
    """

    def test_crr_b1_corporate_firb_low_pd(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B1: Corporate F-IRB with low PD.

        Input: £25m loan, PD 0.10%, LGD 45% (supervisory), M 2.5y
        Expected: RWA calculated using IRB formula
        """
        scenario_id = "CRR-B1"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_CORP_UK_001"
        assert expected["counterparty_reference"] == "CORP_UK_001"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (0.10% = 0.001)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is supervisory (45%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

    def test_crr_b2_corporate_firb_high_pd(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B2: Corporate F-IRB with high PD.

        Input: £5m loan, PD 5.00%, LGD 45%, M 3.0y
        Expected: Higher RWA due to high PD, lower correlation

        Note: Higher PD leads to lower asset correlation (0.130 vs 0.24 at low PD)
        """
        scenario_id = "CRR-B2"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_CORP_UK_005"
        assert expected["counterparty_reference"] == "CORP_UK_005"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (5.00% = 0.05)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is supervisory (45%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

    def test_crr_b3_subordinated_exposure(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B3: Subordinated exposure uses 75% supervisory LGD.

        Input: £2m subordinated loan, PD 1.00%, LGD 75%, M 4.0y
        Expected: Higher RWA due to 75% LGD vs 45% for senior

        CRR Art. 161: Subordinated claims have 75% LGD
        """
        scenario_id = "CRR-B3"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_SUB_001"
        assert expected["counterparty_reference"] == "CORP_UK_004"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (1.00% = 0.01)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is subordinated supervisory (75%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

    def test_crr_b4_financial_collateral(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B4: Financial Collateral - Reduced LGD.

        Input: £5m loan with 50% cash collateral, PD 0.50%
        Expected: Blended LGD (22.5% = 50% × 0% + 50% × 45%)

        CRR Art. 161, 228: Cash collateral reduces LGD to 0%
        """
        scenario_id = "CRR-B4"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_COLL_001"
        assert expected["counterparty_reference"] == "CORP_SME_002"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (0.50% = 0.005)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is blended (22.5% = 0.225)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

    def test_crr_b5_sme_corporate_supporting_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B5: SME Corporate F-IRB with supporting factor.

        Input: £2m loan, PD 2.00%, turnover EUR 25m
        Expected: Both firm size correlation adjustment AND SME supporting factor

        This demonstrates the dual benefit for SME corporates under CRR:
        1. Lower correlation (Art. 153(4))
        2. 0.7619 RWA multiplier (Art. 501)

        Note: Neither adjustment available under Basel 3.1
        """
        scenario_id = "CRR-B5"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_CORP_SME_001"
        assert expected["counterparty_reference"] == "CORP_SME_001"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA (after supporting factor)
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (2.00% = 0.02)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is supervisory (45%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

        # Verify supporting factor is applied (0.7619)
        assert_supporting_factor_match(
            actual=actual.get("supporting_factor", 1.0),
            expected=expected["supporting_factor"],
            scenario_id=scenario_id,
        )

        # Verify RWA is reduced by supporting factor
        assert expected["rwa_after_sf"] < expected["rwa_before_sf"], (
            f"{scenario_id}: RWA should be reduced after supporting factor"
        )

    def test_crr_b6_pd_floor_binding(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B6: PD Floor Binding (0.01% -> 0.03%).

        Input: £1m loan with very low internal PD (0.01%)
        Expected: PD floored to 0.03% (CRR single floor)

        CRR Art. 163: Single PD floor of 0.03% for all non-defaulted exposures
        """
        scenario_id = "CRR-B6"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_CORP_UK_002"
        assert expected["counterparty_reference"] == "CORP_UK_002"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is floored to 0.03% (0.0003)
        # Compare pd_floored (used in calculation) with expected pd (which is floored)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual pd_floored={actual['pd_floored']}, "
            f"expected={expected['pd']} (should be floored to 0.03%)"
        )

        # Verify LGD is supervisory (45%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

    def test_crr_b7_long_maturity_capped(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
        irb_only_results_df: pl.DataFrame,
    ) -> None:
        """
        CRR-B7: Long Maturity Exposure (7Y -> 5Y cap).

        Input: £8m loan with 7 year contractual maturity
        Expected: Maturity capped at 5 years for IRB calculation

        CRR Art. 162: Maturity floor of 1 year, cap of 5 years
        """
        scenario_id = "CRR-B7"
        expected = expected_outputs_dict[scenario_id]
        actual = _get_actual_result(
            irb_only_results_df, expected["exposure_reference"], scenario_id
        )

        # Verify expected output structure matches
        assert expected["exposure_reference"] == "LOAN_LONG_MAT_001"
        assert expected["counterparty_reference"] == "CORP_LRG_001"
        assert expected["approach"] == "F-IRB"

        # Compare actual vs expected RWA
        assert_rwa_within_tolerance(
            actual=actual["rwa"],
            expected=expected["rwa_after_sf"],
            scenario_id=scenario_id,
        )

        # Verify PD is correct (0.80% = 0.008)
        assert actual["pd_floored"] == pytest.approx(expected["pd"], rel=0.01), (
            f"{scenario_id}: PD mismatch - actual={actual['pd']}, expected={expected['pd']}"
        )

        # Verify LGD is supervisory (45%)
        assert actual["lgd"] == pytest.approx(expected["lgd"], rel=0.01), (
            f"{scenario_id}: LGD mismatch - actual={actual['lgd']}, expected={expected['lgd']}"
        )

        # Verify maturity is capped to 5 years
        assert actual["maturity"] == pytest.approx(expected["maturity"], rel=0.01), (
            f"{scenario_id}: Maturity mismatch - actual={actual['maturity']}, "
            f"expected={expected['maturity']} (should be capped to 5 years)"
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
        expected_ids = [f"CRR-B{i}" for i in range(1, 8)]  # Now 7 scenarios (B1-B7)
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

    def test_crr_b_scenarios_have_irb_parameters(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios have required IRB parameters."""
        for scenario in crr_b_scenarios:
            assert scenario["pd"] is not None, (
                f"Scenario {scenario['scenario_id']} missing PD"
            )
            assert scenario["lgd"] is not None, (
                f"Scenario {scenario['scenario_id']} missing LGD"
            )

    def test_crr_b_scenarios_have_expected_loss(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify all CRR-B scenarios have expected loss calculated."""
        for scenario in crr_b_scenarios:
            assert scenario["expected_loss"] is not None, (
                f"Scenario {scenario['scenario_id']} missing expected loss"
            )
            # EL = PD * LGD * EAD
            expected_el = scenario["pd"] * scenario["lgd"] * scenario["ead"]
            assert scenario["expected_loss"] == pytest.approx(expected_el, rel=0.01), (
                f"Scenario {scenario['scenario_id']} EL mismatch"
            )

    def test_crr_b_supervisory_lgd_values(
        self,
        crr_b_scenarios: list[dict[str, Any]],
    ) -> None:
        """Verify F-IRB scenarios use correct supervisory LGD values.

        Note: CRR-B4 is excluded as it tests blended LGD with financial collateral
        (50% × 0% + 50% × 45% = 22.5%), which is a valid F-IRB CRM scenario.
        """
        # CRR-B4 has blended LGD due to financial collateral coverage
        collateral_scenarios = {"CRR-B4"}

        for scenario in crr_b_scenarios:
            if scenario["scenario_id"] in collateral_scenarios:
                # Collateral scenarios have blended LGD, not pure supervisory
                continue

            lgd = scenario["lgd"]
            # F-IRB uses supervisory LGDs: 45% (senior) or 75% (subordinated)
            assert lgd in [0.45, 0.75], (
                f"Scenario {scenario['scenario_id']} has non-supervisory LGD: {lgd}"
            )

    def test_crr_b5_has_sme_supporting_factor(
        self,
        expected_outputs_dict: dict[str, dict[str, Any]],
    ) -> None:
        """Verify CRR-B5 (SME with both adjustments) has supporting factor."""
        scenario = expected_outputs_dict["CRR-B5"]
        assert scenario["supporting_factor"] == pytest.approx(0.7619, rel=0.001), (
            "CRR-B5 should have SME supporting factor 0.7619"
        )
